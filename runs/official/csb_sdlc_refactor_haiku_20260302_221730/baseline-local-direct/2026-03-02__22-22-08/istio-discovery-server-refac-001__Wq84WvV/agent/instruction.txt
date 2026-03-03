# Task: Rename DiscoveryServer to XDSServer

## Objective
Rename `DiscoveryServer` to `XDSServer` in Istio's pilot xDS package to better
describe the server's role as an xDS (discovery service) protocol server.

## Requirements

1. **Rename struct** in `pilot/pkg/xds/discovery.go`:
   - `type DiscoveryServer struct` → `type XDSServer struct`
   - Rename constructor: `NewDiscoveryServer` → `NewXDSServer`

2. **Update all references** (30+ call sites):
   - `pilot/pkg/xds/` — internal package references
   - `pilot/pkg/bootstrap/` — server initialization
   - `pilot/pkg/networking/` — xDS generation
   - Test files

3. **Update receiver methods**

## Key Reference Files
- `pilot/pkg/xds/discovery.go` — struct definition
- `pilot/pkg/bootstrap/server.go` — creates DiscoveryServer
- `pilot/pkg/xds/ads.go` — uses DiscoveryServer

## Success Criteria
- `type DiscoveryServer struct` no longer exists
- `type XDSServer struct` exists
- Constructor renamed
- 80%+ of references updated
