# Static DHCP Leases to DNS over RNDC in OPNSense

## About
This script has been created to synchronise `static` DHCP leases in OPNSense to a Dynamic DNS server over RNDC.  
Use it at your own risk.

## Requirements
- Dynamic DNS (RNDC) configured in the DNS server
- Zones created in the DNS server (including Reverse DNS)
- Domain set in the OPNSense DHCP interface settings
- Static leases created in the OPNSense DHCP interface

## Usage
It can be run from shell with the command `python3 static_dhcp_to_dns.py`. Use the `--help` parameter to get more information.  
Another option is to change the default values in the script and run it without parameters.

### Installation in OPNSense for automatic updates
- Override the default values within the `static_dhcp_to_dns.py` script with your DNS RNDC key.
- Place the `static_dhcp_to_dns.py` script into `/usr/local/opnsense/scripts`
- Place the `static_dhcp_to_dns_run.sh` script into `/usr/local/etc/rc.syshook.d/config` (config folder might have to be created)
- Set the executable flag (chmod +x) on `static_dhcp_to_dns_run.sh`
- Add or remove a static lease in the OPNSense DHCP interface to trigger an update

## Author
Sverto  
https://github.com/Sverto



