#!/usr/bin/env python3
# Author: Sverto (https://github.com/Sverto)
import os
import argparse
import subprocess
import time
import sqlite3
from enum import Enum, IntEnum
from sqlite3 import Error


# defaults
dnsKeyAlgorithm = "hmac-sha512"
dnsKeyName      = "rndc-key"
dnsKey          = "MYKEY=="
dnsTtl          = 3600 # TTL is the time in DNS cache, it doesn't remove the record once the TTL is expired
interval        = 60

opnSenseConfigPath = "/conf/config.xml"
leaseCacheDbPath = "./static_leases.db"


# args
parser = argparse.ArgumentParser(description='''ABOUT
This script has been created to synchronise STATIC DHCP leases in OPNSense to a Dynamic DNS server over RNDC.  
Use it at your own risk.

REQUIREMENTS
- Dynamic DNS (RNDC) configured in the DNS server
- Zones created in the DNS server (including Reverse DNS)
- Domain set in the OPNSense DHCP interface settings
- Static leases created in the OPNSense DHCP interface

USAGE
It can be run from shell with the command python3 "static_dhcp_to_dns.py". Use the "--help" parameter to get more information.  
Another option is to change the default values in the script and run it without parameters.

INSTALLATION IN OPNSENSE FOR AUTOMATIC UPDATES
- Override the default values within the static_dhcp_to_dns.py script with your DNS RNDC key.
- Place the "static_dhcp_to_dns.py" script into "/usr/local/opnsense/scripts"
- Place the "static_dhcp_to_dns_run.sh" script into "/usr/local/etc/rc.syshook.d/config" (config folder might have to be created)
- Set the executable flag (chmod +x) on "static_dhcp_to_dns_run.sh"
- Add or remove a static lease in the OPNSense DHCP interface to trigger an update

AUTHOR
Sverto  
https://github.com/Sverto''',
    formatter_class=argparse.RawTextHelpFormatter) #formatter_class=lambda prog: argparse.HelpFormatter(prog,max_help_position=40,width=max(os.get_terminal_size().columns, 60)))
parser.add_argument("-a", "--algorithm", help="The Dynamic DNS authentication algorithm (default=hmac-sha512)", type=str, default=dnsKeyAlgorithm)
parser.add_argument("-n", "--keyname", help="The Dynamic DNS authentication keyname (default=rndc-key)", type=str, default=dnsKeyName)
parser.add_argument("-k", "--key", help="The Dynamic DNS authentication key/token", type=str, default=dnsKey)
parser.add_argument("-l", "--loop", help="Run continuously every x seconds", action='store_true')
parser.add_argument("-i", "--interval", help="Interval in seconds when running continuously (default=60,min=5)", type=int, default=interval)
parser.add_argument("-f", "--force", help="Force update Dynamic DNS records", action='store_true')
args = parser.parse_args()

if hasattr(args, 'help'):
    parser.print_help()
    exit()

dnsKeyAlgorithm = args.algorithm
dnsKeyName      = args.keyname
dnsKey          = args.key
loop            = args.loop
interval        = args.interval
dnsForceUpdate  = args.force

class LeaseState(IntEnum):
    UNCHANGED = 1
    NEW = 2
    UPDATED = 3
    DELETED = 4


class LeaseType(Enum):
    UNKNOWN = 0
    DHCP = 1
    STATIC = 2

class Lease:
    domain   = None
    hostname = None
    ip       = None
    state = LeaseState.UNCHANGED
    type  = LeaseType.UNKNOWN
    
    def __init__(self, type, domain=None, hostname=None, ip=None):
        self.domain   = domain
        self.hostname = hostname
        self.ip       = ip
        
    def __str__(self):
        return "%s.%s %s" % (self.hostname, self.domain, self.ip)
    

# Get a enumeration of Lease objects
def get_static_leases():
    
    # Get DHCP static leases from OPNSense XML config file 
    # Returns a line for each staticmap item (1 line containing the domain, 1 line containing the hostname, 1 line containing the ip...) in a repeating order
    cmd = ["xmllint", "--xpath", '//*[*[name()=\"staticmap\"]]/domain|//staticmap/hostname|//staticmap/ipaddr', opnSenseConfigPath]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    
    # Process the lines into Lease objects
    slList = []
    sl = Lease(LeaseType.STATIC)
    
    for line in proc.stdout.readlines():
        lineUtf = line.decode('utf-8').rstrip()
        
        if (lineUtf.startswith('<domain>')):
                sl.domain = lineUtf[8:][:-9]
                sl = Lease(LeaseType.STATIC, sl.domain)
            
        elif (lineUtf.startswith('<ipaddr>')):
            if (sl.ip is None):
                sl.ip = lineUtf[8:][:-9]
            else:
                raise Exception('Static lease IPADDR mismatch in domain %s' % sl.domain)
            
        elif (lineUtf.startswith('<hostname>')):
            if (sl.hostname is None):
                sl.hostname = lineUtf[10:][:-11]
            else:
                raise Exception('Static lease HOSTNAME mismatch in domain %s' % sl.domain)
        
        if (sl.domain and sl.ip and sl.hostname):
            slList.append(sl)
            sl = Lease(LeaseType.STATIC, sl.domain)
         
    if (sl.domain and sl.ip and sl.hostname):
            slList.append(sl)
    
    return slList


# Update multiple DNS records from a Lease object list
def dns_update(leases):
    tmpFilePath = '/tmp/lease_update'
    
    # Construct a nsupdate command file
    count = 0
    with open(tmpFilePath, 'w') as f:
        for lease in leases:
            # A
            f.write('update delete %s.%s.\n' % (lease.hostname, lease.domain))
            if (lease.state != LeaseState.DELETED):
                f.write('update add %s.%s. %s A %s\n' % (lease.hostname, lease.domain, dnsTtl, lease.ip))
            f.write('send\n')
            # PTR
            ptrName = '.'.join(lease.ip.split('.')[::-1]) + '.in-addr.arpa'
            f.write('update delete %s\n' % ptrName)
            if (lease.state != LeaseState.DELETED):
                f.write('update add %s %s PTR %s.%s.\n' % (ptrName, dnsTtl, lease.hostname, lease.domain))
            f.write('send\n')
            
    
    # Execute the DNS update (IPv4 localhost)
    cmd = ['nsupdate', '-y', '%s:%s:%s' % (dnsKeyAlgorithm, dnsKeyName, dnsKey), '-l', '-4', tmpFilePath]
    
    subprocess.check_call(cmd)
    print('DNS records updated.')
    
    os.remove(tmpFilePath)
    

# Open file DB connection
def get_db_connection():
    con = None
    try:
        con = sqlite3.connect(leaseCacheDbPath)
        cur = con.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS leases (domain text NOT NULL, hostname text NOT NULL, ip text NOT NULL, PRIMARY KEY (domain, hostname))''')
        cur.close()
    except Error as ex:
        print("Failed to create/open the lease cache database file '%s':\n%s" % (leaseCacheDbPath, ex))
        if con:
            con.close()
    return con
    

# Use DB as cache to detect changes and set the Lease object state accordingly
def db_compare(leases):
    
    con = get_db_connection()
    cur = con.cursor()
    
    # Compare leases with cache and construct sql data objects
    for lease in leases:
        record = cur.execute('''SELECT * FROM leases WHERE domain = ? AND hostname = ?''', (lease.domain, lease.hostname)).fetchone()
        
        # Figure out updated records
        if (record):
            if (record[2] != lease.ip):
                lease.state = LeaseState.UPDATED
        # Figure out new records
        else:
            lease.state = LeaseState.NEW
    
    # Figure out deleted records
    records = cur.execute('''SELECT * FROM leases WHERE NOT (domain, hostname) IN (VALUES {})'''
                                .format( ','.join(['("%s","%s")' % (x.domain, x.hostname) for x in leases]) )).fetchall() # unsafe
    for record in records:
        # Add deleted records to the lease list with state deleted
        lease = Lease(record[0], record[1], record[2])
        lease.state = LeaseState.DELETED
        leases.append(lease)
    
    # Log
    print()
    leases.sort(key=lambda x: x.state)
    for lease in leases:
        print('%s: %s' % (lease.state.name, lease))
    print()
    
    con.close()
    

# Update cache DB with changed leases
def db_update(leases):
    
    # Insert/Update/Delete records from cache DB
    sqlDeletedLeases  = [(y.domain, y.hostname) for y in filter(lambda x: (x.state == LeaseState.DELETED), leases)]
    sqlModifiedLeases = [(y.domain, y.hostname, y.ip) for y in filter(lambda x: (x.state == LeaseState.UPDATED or x.state == LeaseState.NEW), leases)]
    
    con = get_db_connection()
    cur = con.cursor()
    cur.executemany('''DELETE FROM leases WHERE domain = ? AND hostname = ?''', sqlDeletedLeases)
    cur.executemany('''INSERT OR REPLACE INTO leases VALUES (?, ?, ?)''', sqlModifiedLeases)
    con.commit()
    con.close()
    print('Cache DB records updated.')



# === Run ===
while True:
    leases = get_static_leases()
    db_compare(leases)
    
    # Force records update if set
    processableLeases = None
    if (dnsForceUpdate):
        processableLeases = leases
    else:
        # Get list of changed leases
        processableLeases = list(filter(lambda x: (x.state != LeaseState.UNCHANGED), leases))
    
    if len(processableLeases) > 0:
        dns_update(leases)
        db_update(leases)
    else:
        print('Records already up-to-date.')
    print()
    
    if loop != True:
        break
    
    # Only re-evaluate if the OPNSense config file changed
    awaitFileChange = True
    prevModTime = os.stat(opnSenseConfigPath).st_mtime
    
    while awaitFileChange:
        time.sleep(max(interval, 5))
        modTime = os.stat(opnSenseConfigPath).st_mtime
        
        if (modTime != prevModTime or dnsForceUpdate):
            awaitFileChange = False
        else:
            print('No OPNSense config file changes detected.')
    
