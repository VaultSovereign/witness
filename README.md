# Witness Receipt v0

A local, portable prototype of the receipt primitive described in
`attached_assets/THE_RECEIPT_PRIMITIVE_1787186242325.md`.

It creates a small package:

```text
receipt/
├── receipt.json       # canonical machine-readable record
├── receipt.md         # human-readable summary
└── evidence/          # copied evidence with recorded SHA-256 digests
```

## Quick start

```bash
printf 'PR merged at SHA 93fb...\n' > merge-result.txt
python3 witness.py create \
  --out demo-receipt \
  --objective "Merge PR #241 if required checks remain clean, then delete its branch" \
  --scope "witnessops/web, PR #241 only" \
  --success "PR merged and source branch absent" \
  --principal sovereign \
  --actor Codex \
  --boundary "GitHub repository write permission; PR #241 only" \
  --operation "Fetched PR state and required checks" \
  --operation "Merged PR through GitHub API" \
  --operation "Requested source branch deletion" \
  --evidence merge-result.txt \
  --claim "PR #241 merged and source branch absent" \
  --status VERIFIED \
  --verify-mechanism "Authoritative post-mutation GitHub API re-read"

python3 witness.py verify demo-receipt
```

`VERIFIED` is rejected unless a verification mechanism is named. The
`verify` command checks the receipt structure and hashes of retained evidence;
it does not upgrade a `RECORDED`, `BLOCKED`, or `UNRESOLVED` result, and it does
not claim that the original observation was truthful.