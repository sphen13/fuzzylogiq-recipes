#!/usr/bin/python
# encoding: utf-8
"""
MunkiRebrander.py

!!DESCRIPTION GOES HERE!!

Copyright (C) University of Oxford 2017
    Ben Goodstein <ben.goodstein at it.ox.ac.uk>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

from subprocess import Popen, PIPE
import os
import shutil
from tempfile import mkdtemp
from xml.etree import ElementTree as ET
import plistlib
import argparse
import sys
import re
import atexit
import glob
import fnmatch
import io
import json
from autopkglib import Processor, ProcessorError

__all__ = ['MunkiRebrander']

APPNAME = 'Managed Software Center'

APPNAME_LOCALIZED = {
    'da': u'Managed Software Center',
    'de': u'Geführte Softwareaktualisierung',
    'en': u'Managed Software Center',
    'en_AU': u'Managed Software Centre',
    'en_GB': u'Managed Software Centre',
    'en_CA': u'Managed Software Centre',
    'es': u'Centro de aplicaciones',
    'fi': u'Managed Software Center',
    'fr': u'Centre de gestion des logiciels',
    'it': u'Centro Gestione Applicazioni',
    'ja': u'Managed Software Center',
    'nb': u'Managed Software Center',
    'nl': u'Managed Software Center',
    'ru': u'Центр Управления ПО',
    'sv': u'Managed Software Center'
}

MSC_APP = {'path': 'Applications/Managed Software Center.app/Contents/Resources',
           'icon': 'Managed Software Center.icns'}
MS_APP = {'path': os.path.join(MSC_APP['path'], 'MunkiStatus.app/Contents/Resources'),
          'icon': 'MunkiStatus.icns'}

APPS = [MSC_APP, MS_APP]

ICON_SIZES = [('16', '16x16'), ('32', '16x16@2x'),
              ('32', '32x32'), ('64', '32x32@2x'),
              ('128', '128x128'), ('256', '128x128@2x'),
              ('256', '256x256'), ('512', '256x256@2x'),
              ('512', '512x512'), ('1024', '512x512@2x')]

PKGBUILD = '/usr/bin/pkgbuild'
PKGUTIL = '/usr/sbin/pkgutil'
PRODUCTBUILD = '/usr/bin/productbuild'
PRODUCTSIGN = '/usr/bin/productsign'
DITTO = '/usr/bin/ditto'
PLUTIL = '/usr/bin/plutil'
SIPS = '/usr/bin/sips'
ICONUTIL = '/usr/bin/iconutil'
CURL = '/usr/bin/curl'

class MunkiRebrander(Processor):
    '''Rebrands Managed Software Center.app with a new name in all localisations,
    plus an optional icon and postinstall file'''
    description = __doc__
    input_variables = {
        'unpacked_path': {
            'required': True,
            'description': ('Path to unpacked munkitools-app pkg'),
        },
        'app_name': {
            'required': True,
            'description': ('Your desired app name for Managed Software Center'),
        },
        'icon_file': {
            'required': False,
            'description': ('Optional icon file to replace Managed Software '
                            'Center\'s. Can be an .icns file or a 1024x1024 '
                            '.png with alpha channel, in which case it will be '
                            'converted to an .icns.'),
        },
        'postinstall': {
            'required': False,
            'description': ('Optional postinstall file to be added to the '
                            'munkitools-app pkg'),
        },
    }
    output_variables = {}

    def run_cmd(self, cmd, ret=False):
        '''Runs a command passed in as a list. If ret is True, returns stdout'''
        proc = Popen(cmd, stdout=PIPE, stderr=PIPE)
        out, err = proc.communicate()
        output = out
        if proc.returncode is not 0:
            raise ProcessorError(err)
        if ret:
            return output

    def plist_to_xml(self, plist):
        '''Converts plist file to xml1 format'''
        cmd = [PLUTIL, '-convert', 'xml1', plist]
        self.run_cmd(cmd)

    def plist_to_binary(self, plist):
        '''Converts plist file to binary1 format'''
        cmd = [PLUTIL, '-convert', 'binary1', plist]
        self.run_cmd(cmd)

    def replace_strings(self, strings_file, code, appname):
        '''Replaces localized app name in a .strings file with desired app
        name'''
        localized = APPNAME_LOCALIZED[code]
        backup_file = '%s.bak' % strings_file
        with io.open(backup_file, 'w', encoding='utf-16') as fw, \
            io.open(strings_file, 'r', encoding='utf-16') as fr:
            for line in fr:
                # We want to only replace on the right hand side of any =
                # and we don't want to do it to a comment
                if '=' in line and not line.startswith('/*'):
                    left, right = line.split('=')
                    right = right.replace(localized, appname)
                    line = '='.join([left, right])
                fw.write(line)
        os.remove(strings_file)
        os.rename(backup_file, strings_file)

    def replace_nib(self, nib_file, code, appname):
        '''Replaces localized app name in a .nib file with desired app name'''
        localized = APPNAME_LOCALIZED[code]
        backup_file = '%s.bak' % nib_file
        self.plist_to_xml(nib_file)
        with io.open(backup_file, 'w') as fw,  io.open(nib_file, 'r') as fr:
            for line in fr:
                # Simpler than mucking about with plistlib
                line = line.replace(localized, appname)
                fw.write(line)
        os.remove(nib_file)
        os.rename(backup_file, nib_file)
        self.plist_to_binary(nib_file)

    def convert_to_icns(self, png, output_dir):
        '''Takes a png file and attempts to convert it to an icns set'''
        temp_dir = mkdtemp()
        iconset = os.path.join(temp_dir, 'AppIcns.iconset')
        icns = os.path.join(temp_dir, 'AppIcns.icns')
        self.output('Converting %s to .icns...')
        os.mkdir(iconset)
        for hw, suffix in ICON_SIZES:
            cmd = [SIPS, '-z', hw, hw, png,
                   '--out', os.path.join(iconset, 'icon_%s.png' % suffix)]
            self.run_cmd(cmd)
        cmd = [ICONUTIL, '-c', 'icns', iconset,
               '-o', icns]
        self.run_cmd(cmd)
        return icns

    def main(self):
        if "unpacked_path" in self.env and "app_name" in self.env:
            path = self.env['unpacked_path']
            app_name = self.env['app_name']
            self.output("Rebranding %s with app name %s" % (path,
                                                            app_name))
            # Find the lproj directories in the apps' Resources dirs
            for app in APPS:
                resources_dir = os.path.join(path,
                                             app['path'])
                # Get a list of all the lproj dirs in each app's Resources dir
                lproj_dirs = glob.glob(os.path.join(resources_dir, '*.lproj'))
                for lproj_dir in lproj_dirs:
                    # Determine lang code
                    code = os.path.basename(lproj_dir).split('.')[0]
                    # Don't try to change anything we don't know about
                    if code in APPNAME_LOCALIZED.keys():
                        for root, dirs, files in os.walk(lproj_dir):
                            for file_ in files:
                                lfile = os.path.join(root, file_)
                                if fnmatch.fnmatch(lfile, '*.strings'):
                                    self.replace_strings(lfile, code, app_name)
                                if fnmatch.fnmatch(lfile, '*.nib'):
                                    self.replace_nib(lfile, code, app_name)
                if 'icon_file' in self.env:
                    icon_file = self.env['icon_file']
                    if os.path.exists(icon_file):
                        if fnmatch.fnmatch(icon_file, '*.png'):
                            icon_file = self.convert_to_icns(
                                icon_file,
                                self.env['RECIPE_CACHE_DIR']
                            )
                        icon_path = os.path.join(app['path'], app['icon'])
                        dest = os.path.join(path,
                                            icon_path)
                        self.output(
                            "Replacing icons with %s in %s..." % (icon_file,
                                                                  dest)
                        )
                        shutil.copyfile(icon_file, dest)
                    else:
                        raise ProcessorError('%s does not exist!' % icon_file)

if __name__ == '__main__':
    PROCESSOR = MunkiRebrander
    PROCESSOR.execute_shell()
