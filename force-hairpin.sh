#!/bin/bash
# force-hairpin.sh - Force local hairpin via macvlan for inspection lab

set -euo pipefail

SUBNET="192.168.1.0/24"  # Your LAN subnet
GATEWAY="192.168.1.1"    # Your router (for default route if needed; optional for pure local hairpin)
HOST_IF="eno1"           # Main physical NIC

# Deprioritize local route table (do this once)
if ! ip rule show | grep -q "1000:\s*lookup local"; then
    echo "Deprioritizing local route table..."
    ip rule add pref 1000 lookup local
    ip rule del pref 0 lookup local  # Remove default high-prio local
fi

# Disable rp_filter and enable accept_local on eno1 and all macv*
echo "Disabling rp_filter and enabling accept_local..."
for if in $HOST_IF macv*; do
    [ -d "/proc/sys/net/ipv4/conf/$if" ] || continue
    echo 0 > "/proc/sys/net/ipv4/conf/$if/rp_filter"
    echo 1 > "/proc/sys/net/ipv4/conf/$if/accept_local"
done

# Per-macvlan setup
for i in {1..23}; do
    IFACE="macv${i}"
    IP=$(ip -4 addr show "$IFACE" | grep -oP '(?<=inet\s)\d+(\.\d+){3}' || true)

    if [[ -z "$IP" ]]; then
        echo "Skipping $IFACE - no IP"
        continue
    fi

    TABLE=$((1000 + i))  # Tables 1001-1023

    # Add rule: from this IP, use custom table (pref 100 < 1000)
    if ! ip rule show | grep -q "from $IP lookup $TABLE"; then
        echo "Adding rule for $IFACE ($IP): from $IP lookup $TABLE"
        ip rule add from "$IP" lookup "$TABLE" pref 100
    fi

    # In custom table: route local subnet out this dev (forces hairpin)
    if ! ip route show table "$TABLE" | grep -q "$SUBNET dev $IFACE"; then
        echo "Adding local subnet route in table $TABLE: $SUBNET dev $IFACE"
        ip route add "$SUBNET" dev "$IFACE" table "$TABLE"
    fi

    # Optional: default route in table (for external traffic via this IP)
    if ! ip route show table "$TABLE" | grep -q "default via $GATEWAY"; then
        echo "Adding default route in table $TABLE: via $GATEWAY dev $IFACE"
        ip route add default via "$GATEWAY" dev "$IFACE" table "$TABLE"
    fi
done

echo "Setup complete. Verify:"
ip rule show
ip route show table 1001  # Example for macv1
