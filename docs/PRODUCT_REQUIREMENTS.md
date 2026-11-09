# Network Stats — Product Requirements

## Product vision

Network Stats is a continuously enriched network discovery and inventory
application. It must do considerably more than scan a subnet using ping
and TCP ports.

The goal is to discover devices through every practical method, identify
them reliably, collect as much information as possible, and maintain an
accurate inventory of managed devices over time.

## 1. Scanner identity

- The machine running Network Stats must appear in discovery results.
- Identify it as "This device" or an equivalent label.
- Detect its actual network interface IP addresses and MAC addresses.
- Do not mistake Docker bridge interfaces or virtual gateways for the
  physical host.
- Host networking is a deployment requirement.
- The application must work independently of the specific Linux server
  distribution or hardware platform.

## 2. Device discovery

Use multiple complementary discovery mechanisms. TCP and ICMP alone
are insufficient.

Potential mechanisms include:

- ARP and neighbour tables.
- ICMP.
- TCP port scanning.
- UDP discovery and probing.
- mDNS / Bonjour.
- SSDP / UPnP.
- DHCP observation.
- IPv6 Neighbor Discovery.
- Passive network traffic observation.
- Service detection and fingerprinting.

Requirements:

- Combine observations from different discovery mechanisms.
- Record which methods discovered each device.
- Do not assume every device responds to every protocol.
- Support devices that do not respond to ping or expose open TCP ports.
- Keep discovery extensible so new protocols can be added independently.

Passive traffic observation may require additional packet-capture
permissions and capabilities, even when host networking is enabled.

## 3. Device identity and reconciliation

Use the following identity preference:

1. MAC address — primary identity.
2. Hostname — fallback when MAC is unavailable.
3. IP address — last-resort fallback.

Requirements:

- Reconcile observations with existing devices on every scan.
- Avoid duplicate managed devices when IP addresses change or discovery
  methods differ.
- Preserve previous IP addresses and useful identity history.
- Handle missing, randomized, or changing MAC addresses carefully.
- Do not merge unrelated devices solely because they share a hostname
  or IP address.
- When identity is uncertain, prefer keeping records separate over
  incorrectly merging devices.

## 4. Device enrichment

Collect and maintain as much reliable information as possible, including:

- MAC address.
- Manufacturer / OUI.
- Current and previous IP addresses.
- Hostname and DNS names.
- Open ports.
- Detected services and service versions.
- Device type and category.
- Vendor and operating system, when identifiable.
- Discovery methods and observations.
- First seen, last seen, and availability.

Every new scan should enrich existing records when new information
becomes available.

Information quality matters:

- New reliable information should update existing records.
- Missing information must not erase previously known information.
- Less reliable observations must not overwrite more reliable data.
- Preserve the source and time of observations where practical.

## 5. Managed devices

Discovery results and managed devices are separate concepts.

- Discovering a device must not automatically add it to managed devices.
- Users control which devices are managed.
- Users can add discovered devices to managed devices.
- Managed devices are automatically enriched by subsequent scans.
- Users can edit managed device information.
- Users can remove devices from managed devices.
- Removing a managed device must not necessarily erase its discovery
  history or observations.
- Preserve useful history when device addresses or properties change.

## 6. Discovery and managed inventory architecture

Keep these responsibilities conceptually separate:

1. Discovery engine:
   Active probes, passive observations, and service detection.

2. Device identification engine:
   Identity matching, duplicate prevention, and reconciliation.

3. Device enrichment and persistence:
   Merge observations, retain history, and update device records.

4. Managed inventory:
   User-controlled devices, lifecycle, and historical information.

Discovery observations should feed identification and enrichment.
Managed inventory should remain user-controlled.

## 7. Deployment and networking

- Docker host networking is a requirement.
- Do not rely on TrueNAS-specific paths or APIs for core functionality.
- Network-level features should be designed to work on other supported
  Linux Docker hosts.
- Document additional capabilities required for packet capture,
  raw sockets, and other network operations.
- Avoid privileged container mode unless a specific feature genuinely
  requires it.

## 8. Guiding principles

1. Discover broadly: never depend on a single protocol.
2. Identify carefully: MAC first, hostname second, IP last.
3. Enrich continuously: every scan can improve the inventory.
4. Preserve information: missing or weaker observations must not destroy
   better known data.
5. Avoid duplicates: reconcile observations before creating identities.
6. Keep discovery separate from management: users control their inventory.
7. Preserve history: changes in device properties should not erase
   useful historical information.
8. Be platform-independent: do not couple core functionality to one
   NAS vendor or operating system.

## 9. Implementation priorities

1. Host networking requirement and reliable "This device" identification.
2. Device identity reconciliation and automatic enrichment.
3. Managed-device lifecycle, including removal.
4. Expand active discovery protocols.
5. Add passive traffic observation and deeper fingerprinting.

All future features should be evaluated against this product vision.
