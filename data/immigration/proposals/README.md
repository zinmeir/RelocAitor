# Proposals

Put one JSON file per proposed update here, then run `python -m immigration review`.

```json
{
  "route": "GBR-skilled-worker-visa",
  "changes": {"fee": {"amount": 769, "currency": "GBP", "note": "For up to 3 years"}},
  "sources": ["https://www.gov.uk/skilled-worker-visa/how-much-it-costs"],
  "checked": "2027-04-01",
  "evidence": "The exact sentence on the page that supports each value",
  "proposed_by": "who or what drafted this"
}
```

Approval is a person's step: `python -m immigration approve FILE --by "Your Name"`.
Route ids and the fields a proposal may change are listed in docs/IMMIGRATION_DATA.md.
