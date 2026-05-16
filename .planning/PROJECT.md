# PhotoConsole

**A local-first Python CLI agent for safe, confident photo/video consolidation and pruning across multiple sources.**

## Vision

Families and power users accumulate photos and videos across many places: backup drives, cloud storage (Google Photos, OneDrive, Amazon, iCloud), PCs, and phones. Storage limits force tough choices—delete something, or pay for more cloud?

PhotoConsole solves this by:
- **Cataloging** all photos and videos from multiple sources (local disks, rclone-mounted clouds, future: Immich/PhotoPrism)
- **Deduplicating** exact duplicates (by hash) to identify redundancy
- **Consolidating** everything into a single, organized master library on a backup drive
- **Ranking** visually similar shots (for informed deletion) via AI clustering + manual review (post-MVP)

The result: **one clean master library** where you can confidently identify and remove duplicates, knowing what you're keeping and why.

## Problem

- **Scattered media**: Photos exist on clouds, devices, old backups—fragmented and hard to manage
- **Storage pressure**: Hitting limits forces urgent (and often regrettable) deletions
- **Uncertainty**: Don't know which copies are duplicates or which version is best
- **Time-consuming**: Manual deduplication across sources is tedious and error-prone
- **Integration gaps**: Existing tools (Immich, PhotoPrism) don't easily ingest from rclone mounts or arbitrary local paths

PhotoConsole fills this gap: **scan everything, deduplicate fearlessly, consolidate safely.**

## Scope: MVP Focus

### In MVP (Phase 1–2)
- Multi-source scanning: local disks, rclone mounts (Google, OneDrive, Amazon, iCloud)
- Photo/video cataloging with metadata (date, size, hash)
- Exact duplicate detection (by hash)
- Consolidation: organize and copy files to a single backup library (never move)
- CLI interface with progress feedback and dry-run mode
- Safety: no destructive actions without confirmation

### Post-MVP (Phase 3+)
- Visual similarity clustering (AI-powered)
- Immich integration (read/write operations)
- PhotoPrism integration (read/write operations)
- Mobile app or web UI
- Advanced filtering and ranking

## Technical Context

**Scale**: Medium library (10K–100K photos/videos)  
**Approach**: Start minimal, grow iteratively  
**User role**: Planning/scoping focus  
**Built with**: Python, CLI-first  
**Integrations** (MVP): Local files, rclone  
**Integrations** (future): Immich, PhotoPrism  

## Success Criteria

1. ✅ Scan all configured sources without data loss
2. ✅ Accurately identify exact duplicates
3. ✅ Consolidate into a clean, organized master library
4. ✅ Provide dry-run and confirmation workflow
5. ✅ Handle 10K–100K items without performance issues

## Key Constraints

- **Local-first**: All data stays on user's hardware (privacy-first)
- **Safe**: Destructive actions (deletions, consolidation) require explicit confirmation
- **Integrations are optional**: Core tool works standalone with local + rclone sources
- **Speed matters**: Scanning and hashing 100K+ items must be fast enough for interactive use

## Timeline

- **Phase 1** (MVP foundation): Scanning, cataloging, exact dedup
- **Phase 2** (MVP completion): Consolidation, safety, CLI polish
- **Phase 3+** (post-MVP): Clustering, integrations, UI enhancements

---

**Created**: 2026-05-16  
**Last Updated**: 2026-05-16
