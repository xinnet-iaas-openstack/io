# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright 2011 OpenStack LLC
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import os
import subprocess

from nova.rootwrap import filters
from nova.rootwrap import wrapper
from nova import test


class RootwrapTestCase(test.TestCase):

    def setUp(self):
        super(RootwrapTestCase, self).setUp()
        self.filters = [
            filters.RegExpFilter("/bin/ls", "root", 'ls', '/[a-z]+'),
            filters.CommandFilter("/usr/bin/foo_bar_not_exist", "root"),
            filters.RegExpFilter("/bin/cat", "root", 'cat', '/[a-z]+'),
            filters.CommandFilter("/nonexistant/cat", "root"),
            filters.CommandFilter("/bin/cat", "root")  # Keep this one last
            ]

    def tearDown(self):
        super(RootwrapTestCase, self).tearDown()

    def test_RegExpFilter_match(self):
        usercmd = ["ls", "/root"]
        filtermatch = wrapper.match_filter(self.filters, usercmd)
        self.assertFalse(filtermatch is None)
        self.assertEqual(filtermatch.get_command(usercmd),
            ["/bin/ls", "/root"])

    def test_RegExpFilter_reject(self):
        usercmd = ["ls", "root"]
        filtermatch = wrapper.match_filter(self.filters, usercmd)
        self.assertTrue(filtermatch is None)

    def test_missing_command(self):
        usercmd = ["foo_bar_not_exist"]
        filtermatch = wrapper.match_filter(self.filters, usercmd)
        self.assertTrue(filtermatch is None)

    def test_DnsmasqFilter(self):
        usercmd = ['FLAGFILE=A', 'NETWORK_ID=foobar', 'dnsmasq', 'foo']
        f = filters.DnsmasqFilter("/usr/bin/dnsmasq", "root")
        self.assertTrue(f.match(usercmd))
        self.assertEqual(f.get_command(usercmd), ['/usr/bin/dnsmasq', 'foo'])
        env = f.get_environment(usercmd)
        self.assertEqual(env.get('FLAGFILE'), 'A')
        self.assertEqual(env.get('NETWORK_ID'), 'foobar')

    @test.skip_if(not os.path.exists("/proc/%d" % os.getpid()),
                  "Test requires /proc filesystem (procfs)")
    def test_KillFilter(self):
        p = subprocess.Popen(["/bin/sleep", "5"])
        f = filters.KillFilter("/bin/kill", "root",
                               ["-ALRM"],
                               ["/bin/sleep"])
        usercmd = ['kill', '-9', p.pid]
        # Incorrect signal should fail
        self.assertFalse(f.match(usercmd))
        usercmd = ['kill', p.pid]
        # Providing no signal should fail
        self.assertFalse(f.match(usercmd))

        f = filters.KillFilter("/bin/kill", "root",
                               ["-9", ""],
                               ["/bin/sleep"])
        usercmd = ['kill', '-9', os.getpid()]
        # Our own PID does not match /bin/sleep, so it should fail
        self.assertFalse(f.match(usercmd))
        usercmd = ['kill', '-9', 999999]
        # Nonexistant PID should fail
        self.assertFalse(f.match(usercmd))
        usercmd = ['kill', p.pid]
        # Providing no signal should work
        self.assertTrue(f.match(usercmd))
        usercmd = ['kill', '-9', p.pid]
        # Providing -9 signal should work
        self.assertTrue(f.match(usercmd))

    def test_skips(self):
        # Check that all filters are skipped and that the last matches
        usercmd = ["cat", "/"]
        filtermatch = wrapper.match_filter(self.filters, usercmd)
        self.assertTrue(filtermatch is self.filters[-1])
