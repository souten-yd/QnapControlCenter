# Development, PR, merge and QPKG release playbook

1. Read latest main README, manifests, packaging, workflows, runtime and tests. Create a narrowly scoped feature branch from main; never push feature work directly to main.
2. Implement one milestone in small commits on the same branch; push updates to the PR. Minimize CI reruns and avoid cosmetic churn.
3. Add or update tests, docs, dependencies and QPKG manifest as applicable. Verify Python compilation, unittest discovery, safety grep and the actual source paths on the branch.
4. Open a PR against main with scope, allowed files, forbidden changes, tested commands, acceptance checks, expected final state, release implications and unresolved limits.
5. Review PR diff AND actual main/branch files; ensure no unexpected changes, startup build steps, execution endpoints, excessive permissions, default exposure, unverified update installation or auto-merge bypass.
6. Merge only after milestone checks and CI pass; prefer squash when allowed, otherwise repository-supported merge method. Re-read main files after merge to ensure intended contents are present.
7. QPKG release: verify reproducible artifact against target QTS 5.x architecture, install/upgrade/uninstall behavior and clean restart. Generate SHA256SUMS; upload matching QPKG and checksums to versioned GitHub Release. Validate downloaded checksum and smoke-test the UI and monitor on device. Do not publish a release when a working QPKG is absent.
8. Web update path: GitHub release discovery => display changelog, asset, hash and version => user confirms => verified QTS upgrade => health check/rollback. Steps after discovery remain blocked pending QTS device verification; do not silently deploy unverified firmware packages.
9. Document exact PR, merge SHA, workflow run, release URL, checksums and observed device validation in release notes. No unverified claims of success.

Safety contract: read-only monitoring; no autonomous process stop/reboot, command execution, raw source serving, arbitrary URL fetching, auto-installing unsigned assets, or startup npm build.
