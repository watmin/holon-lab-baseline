# WordPress Traffic Generator - Networking Setup

This documents the hairpin routing configuration for simulating organic traffic from multiple source IPs.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Host                                                           │
│                                                                 │
│  ┌──────────────┐     ┌─────────────────────────────────────┐  │
│  │ Python       │     │ Squid Proxy                         │  │
│  │ Traffic Gen  │────▶│ Ports 40001-40023                   │  │
│  │ (Playwright) │     │ Each port binds to a macvlan IP     │  │
│  └──────────────┘     └─────────────┬───────────────────────┘  │
│                                     │                           │
│  ┌──────────────────────────────────┼───────────────────────┐  │
│  │ macv1-macv23 interfaces          ▼                       │  │
│  │ (192.168.1.x each, via DHCP)                             │  │
│  │ Policy routing ensures traffic egresses via correct IF   │  │
│  └──────────────────────────────────┬───────────────────────┘  │
│                                     │                           │
└─────────────────────────────────────┼───────────────────────────┘
                                      │ eno1 (physical NIC)
                                      ▼
                            ┌─────────────────┐
                            │  LAN / Switch   │
                            └────────┬────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  Docker macvlan network (lanbridge)                             │
│  Nginx container: 192.168.1.200                                 │
│  Appears as separate host on LAN                                │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Squid Proxy with Multi-IP Egress
- **Config**: `/etc/squid/squid.conf`
- **Ports**: 40001-40023 (23 total, one per macvlan)
- Each port uses `tcp_outgoing_address` to bind to a specific macvlan IP

### 2. Macvlan Interfaces (Host)
- **Interfaces**: `macv1` through `macv23`
- **Parent**: `eno1`
- **IPs**: Assigned via DHCP from LAN router
- Created by `setup-squid-macvlans.sh`

### 3. Policy-Based Routing (Hairpin)
- Each macvlan IP has a dedicated routing table (1001-1023)
- `ip rule` entries route traffic by source IP
- Disables rp_filter and enables accept_local for hairpin
- Ensures packets egress via the correct macvlan interface
- Created by `force-hairpin.sh`

### 4. Docker Macvlan Network
- **Network**: `lanbridge`
- **Subnet**: `192.168.1.0/24`
- **Gateway**: `192.168.1.1`
- Nginx container gets static IP `192.168.1.200`

### 5. DNS Resolution
- `/etc/hosts` contains: `192.168.1.200 wp-lab`
- WordPress site URL set to `https://wp-lab`

---

## After Reboot: Restore Networking

Macvlan interfaces and routing rules do not persist across reboots. Run these steps:

### Step 1: Create macvlan interfaces and configure Squid

```bash
cd ~/wordpress-lemp
sudo ./setup-squid-macvlans.sh
```

This will:
- Create macv1-macv23 interfaces on eno1
- Request DHCP leases for each
- Generate `/etc/squid/squid.conf` with correct IP bindings
- Restart Squid

### Step 2: Set up hairpin routing

```bash
sudo ./force-hairpin.sh
```

This will:
- Deprioritize local route table for hairpin
- Disable rp_filter, enable accept_local
- Create routing tables 1001-1023
- Add routes and `ip rule` entries for source-based routing

### Step 3: Start the WordPress stack

```bash
cd ~/wordpress-lemp
docker compose up -d
```

### Step 4: Verify

```bash
# Test hairpin through Squid
curl -sx http://127.0.0.1:40001 -k https://wp-lab | head -3

# Check macvlan IPs
ip -4 addr show | grep -E 'macv[0-9]+' | head -5

# Check routing rules
ip rule show | grep -E 'from 192\.168\.1\.' | head -5
```

---

## Quick Reference

| Component | Command |
|-----------|---------|
| View macvlan IPs | `ip -4 addr show type macvlan` |
| View routing rules | `ip rule show` |
| View routing table 1001 | `ip route show table 1001` |
| Squid status | `systemctl status squid` |
| Squid logs | `tail -f /var/log/squid/access.log` |
| Docker network | `docker network inspect wordpress-lemp_lanbridge` |
| Nginx container IP | `docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' wordpress-lemp-nginx-1` |

---

## Troubleshooting

### Traffic not hairpinning (stays in kernel)
- Check policy routing: `ip rule show | grep 192.168.1`
- Run `force-hairpin.sh` again

### Squid returning ERR_CANNOT_FORWARD
- Check Squid can resolve hostname: `getent hosts wp-lab`
- Restart Squid after `/etc/hosts` changes: `sudo systemctl restart squid`

### tcpdump verification
```bash
# Watch macvlan egress
sudo tcpdump -i macv1 -n host 192.168.1.200 and port 443

# Watch physical NIC (confirms hairpin)
sudo tcpdump -i eno1 -n host 192.168.1.200 and port 443

# Watch Nginx container ingress
NGINX_PID=$(docker inspect -f '{{.State.Pid}}' wordpress-lemp-nginx-1)
sudo nsenter -t $NGINX_PID -n tcpdump -i eth1 -n port 443
```

---

## Files

| File | Purpose |
|------|---------|
| `setup-squid-macvlans.sh` | Creates macvlan interfaces, configures Squid |
| `force-hairpin.sh` | Sets up hairpin routing for traffic inspection |
| `docker-compose.yml` | WordPress stack with macvlan network |
| `wordpress_traffic_generator.py` | Main traffic generator script |
| `/etc/squid/squid.conf` | Squid proxy config (auto-generated) |
| `/etc/hosts` | Local DNS (wp-lab → 192.168.1.200) |
