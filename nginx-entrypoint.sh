#!/bin/sh
# Get DHCP lease on the macvlan interface
# This runs as part of nginx container startup

set -e

# Install dhcp client if not present
if ! command -v dhclient >/dev/null 2>&1 && ! command -v udhcpc >/dev/null 2>&1; then
    apt-get update -qq && apt-get install -y -qq isc-dhcp-client >/dev/null 2>&1 || true
fi

# Find the macvlan interface by looking for 192.168.x.x subnet
MACVLAN_IF=""
for iface in eth0 eth1 eth2; do
    if ip addr show "$iface" 2>/dev/null | grep -q "192.168.1"; then
        MACVLAN_IF="$iface"
        break
    fi
done

if [ -n "$MACVLAN_IF" ]; then
    echo "Requesting DHCP lease on $MACVLAN_IF (macvlan interface)..."
    if command -v dhclient >/dev/null 2>&1; then
        dhclient -v "$MACVLAN_IF" 2>&1 || echo "DHCP failed, continuing anyway"
    elif command -v udhcpc >/dev/null 2>&1; then
        udhcpc -i "$MACVLAN_IF" -q || echo "DHCP failed, continuing anyway"
    fi
    
    # Show the IP we got
    echo "Macvlan interface $MACVLAN_IF addresses:"
    ip addr show "$MACVLAN_IF" | grep "inet " || true
else
    echo "No macvlan interface (192.168.1.x) found, skipping DHCP"
fi
