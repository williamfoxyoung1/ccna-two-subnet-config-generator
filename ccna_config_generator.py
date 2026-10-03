#!/usr/bin/env python3
"""
Cisco VLSM + Config Generator

Prompts for:
  1. Network IPv4 address/prefix
  2. Required hosts in Subnet A
  3. Required hosts in Subnet B

Generates:
  - ROUTER_Config.txt
  - SW1_Config.txt
  - IP_Addressing_Summary.txt
  - PC-A_IP_Config.txt
  - PC-B_IP_Config.txt

Subnet assignment:
  Subnet A -> ROUTER G0/0/1
  Subnet B -> ROUTER G0/0/0
  First usable IPv4 -> Router
  Last usable IPv4 -> PC
  Second usable IPv4 of Subnet A -> SW1

IPv6 assignment:
  Subnet A -> 2001:145:25:1::/64
  Subnet B -> 2001:145:25:2::/64
  Router   -> ::1
  SW1      -> ::2
  PCs      -> ::10
  Router link-local gateway -> FE80::1
"""

import ipaddress
import math
from pathlib import Path


# ============================================================
# SUBNET CALCULATIONS
# ============================================================

def required_prefix(hosts: int) -> int:
    """Return the smallest normal IPv4 subnet supporting the hosts."""

    if hosts < 1:
        raise ValueError(
            "Host requirement must be at least 1."
        )

    # Add 2 for network and broadcast addresses.
    host_bits = math.ceil(
        math.log2(hosts + 2)
    )

    prefix = 32 - host_bits

    # /31 and /32 do not fit this assignment's
    # traditional host-addressing model.
    if prefix > 30:
        prefix = 30

    return prefix


def subnet_info(
    network: ipaddress.IPv4Network,
    requested_hosts: int
) -> dict:

    usable = network.num_addresses - 2

    binary = ".".join(
        f"{int(octet):08b}"
        for octet in str(
            network.netmask
        ).split(".")
    )

    return {
        "network": network,
        "prefix": network.prefixlen,
        "mask": network.netmask,
        "binary_mask": binary,
        "broadcast": network.broadcast_address,
        "first": network.network_address + 1,
        "second": network.network_address + 2,
        "last": network.broadcast_address - 1,
        "usable": usable,
        "requested": requested_hosts,
    }


# ============================================================
# USER INPUT
# ============================================================

def get_network() -> ipaddress.IPv4Network:

    while True:

        raw = input(
            "Enter the assigned Network IP address "
            "(example: 145.25.35.0 or 145.25.35.0/24): "
        ).strip()

        # If only an IP/network address is supplied,
        # assume /24.
        if "/" not in raw:
            raw += "/24"

        try:

            entered = ipaddress.IPv4Network(
                raw,
                strict=True
            )

            return entered

        except ValueError as exc:

            print(
                f"Invalid network: {exc}"
            )

            print(
                "Enter the NETWORK address, "
                "not a host address.\n"
            )


def get_hosts(name: str) -> int:

    while True:

        raw = input(
            f"Enter number of hosts required "
            f"in Subnet {name}: "
        ).strip()

        try:

            hosts = int(raw)

            if hosts < 1:
                raise ValueError

            return hosts

        except ValueError:

            print(
                "Please enter a whole number "
                "greater than 0.\n"
            )


# ============================================================
# VLSM ALLOCATION
# ============================================================

def allocate_vlsm(
    base: ipaddress.IPv4Network,
    requirements: dict
) -> dict:

    """
    Allocate the largest subnet first.

    Results remain labeled A and B according
    to the user's original requirements.
    """

    ordered = sorted(
        requirements.items(),
        key=lambda item: (
            -item[1],
            item[0]
        )
    )

    cursor = int(
        base.network_address
    )

    end = int(
        base.broadcast_address
    )

    allocations = {}

    for name, hosts in ordered:

        prefix = required_prefix(
            hosts
        )

        if prefix < base.prefixlen:

            raise ValueError(
                f"Subnet {name} needs /{prefix}, "
                f"which is larger than the supplied "
                f"{base.with_prefixlen} network."
            )

        block_size = (
            2 ** (32 - prefix)
        )

        # Align to a valid subnet boundary.
        cursor = (
            (
                cursor
                + block_size
                - 1
            )
            // block_size
        ) * block_size

        subnet_end = (
            cursor
            + block_size
            - 1
        )

        if (
            cursor
            < int(base.network_address)
            or subnet_end > end
        ):

            raise ValueError(
                "The requested Subnet A and "
                "Subnet B host counts do not fit "
                f"inside {base.with_prefixlen}."
            )

        subnet = ipaddress.IPv4Network(
            (cursor, prefix)
        )

        allocations[name] = subnet_info(
            subnet,
            hosts
        )

        cursor += block_size

    # Defensive overlap check.
    a = allocations["A"]["network"]
    b = allocations["B"]["network"]

    if a.overlaps(b):

        raise RuntimeError(
            "Internal error: calculated "
            "subnets overlap."
        )

    return allocations


# ============================================================
# ROUTER CONFIG
# ============================================================

def build_router(
    a: dict,
    b: dict
) -> str:

    return f"""enable
configure terminal
no ip domain lookup
hostname ROUTER
ip domain-name ccna-lab.com
enable secret ciscoenpass

line console 0
 password ciscoconpass
 login
 exit

security passwords min-length 10
username admin secret admin1pass

line vty 0 15
 login local
 transport input ssh
 exit

service password-encryption
banner motd #Illegal Access is Illegal!#
ipv6 unicast-routing

interface g0/0/0
 description Connect to Subnet B
 ip address {b['first']} {b['mask']}
 ipv6 address FE80::1 link-local
 ipv6 address 2001:145:25:2::1/64
 no shutdown
 exit

interface g0/0/1
 description Connect to Subnet A
 ip address {a['first']} {a['mask']}
 ipv6 address FE80::1 link-local
 ipv6 address 2001:145:25:1::1/64
 no shutdown
 exit

crypto key generate rsa modulus 1024
end
copy running-config startup-config
"""


# ============================================================
# SWITCH CONFIG
# ============================================================

def build_switch(
    a: dict
) -> str:

    return f"""enable
configure terminal
no ip domain lookup
hostname SW1
ip domain-name ccna-lab.com
enable secret ciscoenpass

line console 0
 password ciscoconpass
 login
 exit

interface range f0/1-4, f0/7-24, g0/1-2
 shutdown
 exit

username admin secret admin1pass

line vty 0 15
 login local
 transport input ssh
 exit

service password-encryption
banner motd #Illegal Access is Illegal!#

crypto key generate rsa modulus 1024

interface vlan 1
 description Switch Subnet A
 ip address {a['second']} {a['mask']}
 ipv6 address FE80::2 link-local
 ipv6 address 2001:145:25:1::2/64
 no shutdown
 exit

ip default-gateway {a['first']}
end
copy running-config startup-config
"""


# ============================================================
# PC CONFIGURATION TABLE
# ============================================================

def build_pc_config(
    pc_name: str,
    subnet_name: str,
    ipv4_address,
    subnet_mask,
    ipv4_gateway,
    ipv6_address: str,
    ipv6_gateway: str
) -> str:

    """
    Build a separate fixed-width table for a PC.

    """

    rows = [
        (
            "Device",
            pc_name
        ),
        (
            "Subnet",
            subnet_name
        ),
        (
            "IPv4 Address",
            str(ipv4_address)
        ),
        (
            "Subnet Mask",
            str(subnet_mask)
        ),
        (
            "IPv4 Default Gateway",
            str(ipv4_gateway)
        ),
        (
            "IPv6 Address",
            ipv6_address
        ),
        (
            "IPv6 Prefix Length",
            "64"
        ),
        (
            "IPv6 Default Gateway",
            ipv6_gateway
        )
    ]

    field_width = max(
        len(field)
        for field, value in rows
    )

    value_width = max(
        len(value)
        for field, value in rows
    )

    field_width = max(
        field_width,
        len("SETTING")
    )

    value_width = max(
        value_width,
        len("VALUE")
    )

    border = (
        "+"
        + "-" * (field_width + 2)
        + "+"
        + "-" * (value_width + 2)
        + "+"
    )

    lines = [
        f"{pc_name} IP CONFIGURATION",
        "=" * len(
            f"{pc_name} IP CONFIGURATION"
        ),
        "",
        border,
        (
            f"| {'SETTING':<{field_width}} "
            f"| {'VALUE':<{value_width}} |"
        ),
        border
    ]

    for field, value in rows:

        lines.append(
            f"| {field:<{field_width}} "
            f"| {value:<{value_width}} |"
        )

    lines.append(
        border
    )

    lines.extend(
        [
            "",
            "STATIC CONFIGURATION",
            "--------------------",
            f"IPv4 Address:          {ipv4_address}",
            f"Subnet Mask:           {subnet_mask}",
            f"IPv4 Default Gateway:  {ipv4_gateway}",
            "",
            f"IPv6 Address:          {ipv6_address}",
            "IPv6 Prefix Length:    64",
            f"IPv6 Default Gateway:  {ipv6_gateway}",
            ""   
        ]
    )

    return "\n".join(
        lines
    ) + "\n"


# ============================================================
# ADDRESSING SUMMARY
# ============================================================

def build_summary(
    base,
    a: dict,
    b: dict
) -> str:

    def section(
        name,
        s
    ):

        borrowed = (
            s["prefix"]
            - base.prefixlen
        )

        possible_subnets = (
            2 ** borrowed
            if borrowed >= 0
            else 0
        )

        return f"""SUBNET {name}
---------
Required hosts:              {s['requested']}
Number of bits in subnet:    {borrowed}
IP mask (binary):            {s['binary_mask']}
New IP mask (decimal):       {s['mask']}
CIDR prefix:                 /{s['prefix']}
Maximum usable subnets*:     {possible_subnets}
Usable hosts in this subnet: {s['usable']}
IP subnet:                   {s['network'].network_address}
First usable host:           {s['first']}
Last usable host:            {s['last']}
Broadcast address:           {s['broadcast']}
"""

    return f"""Cisco VLSM + Config Generator - IP ADDRESSING SUMMARY
===================================================
Assigned network: {base.with_prefixlen}

{section("A", a)}
{section("B", b)}

DEVICE ADDRESSING
-----------------

PC-A
  IPv4 Address:         {a['last']}
  Subnet Mask:          {a['mask']}
  IPv4 Gateway:         {a['first']}
  IPv6 Address:         2001:145:25:1::10/64
  IPv6 Gateway:         FE80::1

ROUTER G0/0/1 (Subnet A)
  IPv4 Address:         {a['first']}
  Subnet Mask:          {a['mask']}
  IPv6 Address:         2001:145:25:1::1/64
  IPv6 Link-local:      FE80::1

SW1 VLAN 1
  IPv4 Address:         {a['second']}
  Subnet Mask:          {a['mask']}
  IPv4 Gateway:         {a['first']}
  IPv6 Address:         2001:145:25:1::2/64
  IPv6 Link-local:      FE80::2

ROUTER G0/0/0 (Subnet B)
  IPv4 Address:         {b['first']}
  Subnet Mask:          {b['mask']}
  IPv6 Address:         2001:145:25:2::1/64
  IPv6 Link-local:      FE80::1

PC-B
  IPv4 Address:         {b['last']}
  Subnet Mask:          {b['mask']}
  IPv4 Gateway:         {b['first']}
  IPv6 Address:         2001:145:25:2::10/64
  IPv6 Gateway:         FE80::1


IPv6 SUBNETS
------------

Subnet A:
  2001:145:25:1::/64

Subnet B:
  2001:145:25:2::/64


* "Maximum usable subnets" is shown relative
  to the supplied base prefix.
"""


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 62
    )

    print(
        " Cisco VLSM + Config Generator"
    )

    print(
        "=" * 62
    )

    print()

    # --------------------------------------------------------
    # INPUT
    # --------------------------------------------------------

    base = get_network()

    hosts_a = get_hosts(
        "A"
    )

    hosts_b = get_hosts(
        "B"
    )

    # --------------------------------------------------------
    # CALCULATE
    # --------------------------------------------------------

    try:

        subnets = allocate_vlsm(
            base,
            {
                "A": hosts_a,
                "B": hosts_b
            }
        )

    except (
        ValueError,
        RuntimeError
    ) as exc:

        print(
            f"\nERROR: {exc}"
        )

        print(
            "No configuration files "
            "were created."
        )

        return

    a = subnets["A"]
    b = subnets["B"]

    # --------------------------------------------------------
    # OUTPUT DIRECTORY
    # --------------------------------------------------------

    output_dir = Path(
        "CCNA_Config_Output"
    )

    output_dir.mkdir(
        exist_ok=True
    )

    # --------------------------------------------------------
    # BUILD PC CONFIGURATION FILES
    # --------------------------------------------------------

    pc_a_config = build_pc_config(
        pc_name="PC-A",
        subnet_name="Subnet A",
        ipv4_address=a["last"],
        subnet_mask=a["mask"],
        ipv4_gateway=a["first"],
        ipv6_address="2001:145:25:1::10/64",
        ipv6_gateway="FE80::1"
    )

    pc_b_config = build_pc_config(
        pc_name="PC-B",
        subnet_name="Subnet B",
        ipv4_address=b["last"],
        subnet_mask=b["mask"],
        ipv4_gateway=b["first"],
        ipv6_address="2001:145:25:2::10/64",
        ipv6_gateway="FE80::1"
    )

    # --------------------------------------------------------
    # ALL OUTPUT FILES
    # --------------------------------------------------------

    files = {

        "ROUTER_Config.txt":
            build_router(
                a,
                b
            ),

        "SW1_Config.txt":
            build_switch(
                a
            ),

        "IP_Addressing_Summary.txt":
            build_summary(
                base,
                a,
                b
            ),

        "PC-A_IP_Config.txt":
            pc_a_config,

        "PC-B_IP_Config.txt":
            pc_b_config
    }

    # --------------------------------------------------------
    # WRITE FILES
    # --------------------------------------------------------

    for filename, contents in files.items():

        file_path = (
            output_dir
            / filename
        )

        file_path.write_text(
            contents,
            encoding="utf-8"
        )

    # --------------------------------------------------------
    # CONSOLE RESULTS
    # --------------------------------------------------------

    print()
    print(
        "VALIDATION PASSED"
    )

    print(
        "-" * 62
    )

    print(
        f"Base network : "
        f"{base.with_prefixlen}"
    )

    print(
        f"Subnet A     : "
        f"{a['network'].with_prefixlen:<18} "
        f"Mask {a['mask']} | "
        f"{a['usable']} usable hosts"
    )

    print(
        f"Subnet B     : "
        f"{b['network'].with_prefixlen:<18} "
        f"Mask {b['mask']} | "
        f"{b['usable']} usable hosts"
    )

    print(
        "Overlap      : No"
    )

    # --------------------------------------------------------
    # PC-A
    # --------------------------------------------------------

    print()
    print(
        "PC-A Configuration:"
    )

    print(
        f"  IPv4 Address : "
        f"{a['last']}"
    )

    print(
        f"  Subnet Mask  : "
        f"{a['mask']}"
    )

    print(
        f"  IPv4 Gateway : "
        f"{a['first']}"
    )

    print(
        "  IPv6 Address : "
        "2001:145:25:1::10/64"
    )

    print(
        "  IPv6 Gateway : "
        "FE80::1"
    )

    # --------------------------------------------------------
    # PC-B
    # --------------------------------------------------------

    print()
    print(
        "PC-B Configuration:"
    )

    print(
        f"  IPv4 Address : "
        f"{b['last']}"
    )

    print(
        f"  Subnet Mask  : "
        f"{b['mask']}"
    )

    print(
        f"  IPv4 Gateway : "
        f"{b['first']}"
    )

    print(
        "  IPv6 Address : "
        "2001:145:25:2::10/64"
    )

    print(
        "  IPv6 Gateway : "
        "FE80::1"
    )

    # --------------------------------------------------------
    # FILE RESULTS
    # --------------------------------------------------------

    print()
    print(
        f"Files saved in:\n"
        f"{output_dir.resolve()}"
    )

    print()

    for filename in files:

        print(
            f"  - {filename}"
        )


if __name__ == "__main__":
    main()
