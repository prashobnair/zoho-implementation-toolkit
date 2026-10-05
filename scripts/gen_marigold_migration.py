"""Deterministic Marigold migration export generator (TK-MIG-F9..F11 seed data).

Writes a synthetic Pipedrive-shaped export (~2,000 rows) with seeded
defects covering every migration finding code, plus the mapping, target
field metadata, users, a target-existing snapshot, EXPECTED.md and the
machine-readable answer key. Everything is synthetic (``example.invalid``
mailboxes, ``+91 900000000x``-style numbers, invented names) and fully
seeded: reruns are byte-identical.

Usage: ``uv run python scripts/gen_marigold_migration.py [--out DIR]``.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "fixtures" / "migration" / "marigold"

SEED = 20261004

N_PERSONS = 800
N_ORGANIZATIONS = 200
N_DEALS = 700
N_ACTIVITIES = 300

ACTIVE_OWNER = "owner@example.invalid"
INACTIVE_OWNER = "former@example.invalid"
UNKNOWN_OWNER = "ghost@example.invalid"
RETURNING_EMAIL = "returning@example.invalid"

FIRST = [
    "Aarav",
    "Meera",
    "Zara",
    "Arjun",
    "Diya",
    "Kabir",
    "Anaya",
    "Vivaan",
    "Ishaan",
    "Priya",
    "Rohan",
    "Sneha",
    "Aditya",
    "Kavya",
    "Nikhil",
    "Pooja",
    "Rahul",
    "Simran",
    "Varun",
    "Anika",
    "Dev",
    "Riya",
    "Aisha",
    "Karan",
    "Neha",
    "Sahil",
    "Tara",
    "Yash",
    "Ira",
    "Om",
    "Gauri",
    "Harsh",
    "Jaya",
    "Kunal",
    "Lata",
    "Mohan",
    "Naina",
    "Omar",
    "Payal",
    "Qasim",
]
LAST = [
    "Sharma",
    "Rao",
    "Khan",
    "Patel",
    "Iyer",
    "Gupta",
    "Nair",
    "Singh",
    "Reddy",
    "Das",
    "Kulkarni",
    "Menon",
    "Chopra",
    "Bose",
    "Pillai",
    "Joshi",
    "Verma",
    "Agarwal",
    "Mishra",
    "Yadav",
    "Kaur",
    "Bhatt",
    "Chauhan",
    "Desai",
]

CITIES = [
    "Kochi",
    "Jaipur",
    "Indore",
    "Surat",
    "Nagpur",
    "Bhopal",
    "Patna",
    "Ranchi",
    "Guwahati",
    "Dehradun",
    "Shimla",
    "Panaji",
    "Mysuru",
    "Coimbatore",
    "Madurai",
    "Vijayawada",
    "Visakhapatnam",
    "Lucknow",
    "Kanpur",
    "Agra",
    "Meerut",
    "Varanasi",
    "Allahabad",
    "Jabalpur",
    "Gwalior",
    "Raipur",
    "Bhubaneswar",
    "Cuttack",
    "Rourkela",
    "Jamshedpur",
    "Dhanbad",
    "Bokaro",
    "Asansol",
    "Durgapur",
    "Siliguri",
    "Howrah",
    "Kharagpur",
    "Haldia",
    "Portsmouth",
    "Seabrook",
]
TRADES = [
    "Spices",
    "Textiles",
    "Ceramics",
    "Logistics",
    "Foods",
    "Metals",
    "Timber",
    "Chemicals",
    "Paper",
    "Glass",
    "Leather",
    "Granite",
    "Marble",
    "Tea",
    "Coffee",
    "Rubber",
    "Jute",
    "Silk",
    "Cotton",
    "Pharma",
]

#: Distinctive name closers so unrelated companies never fuzzy-match.
CLOSER_ADJECTIVES = [
    "Emerald",
    "Ruby",
    "Sapphire",
    "Amber",
    "Jade",
    "Opal",
    "Topaz",
    "Garnet",
    "Ivory",
    "Ebony",
    "Crimson",
    "Azure",
    "Golden",
    "Silver",
    "Copper",
    "Bronze",
    "Pearl",
    "Coral",
    "Onyx",
    "Quartz",
]
CLOSER_NOUNS = [
    "Falcon",
    "Banyan",
    "Heron",
    "Lotus",
    "Mango",
    "Peacock",
    "Tiger",
    "River",
    "Monsoon",
    "Desert",
    "Valley",
    "Harbor",
    "Meadow",
    "Summit",
    "Canyon",
    "Lagoon",
    "Orchard",
    "Prairie",
    "Reef",
    "Savanna",
]

STAGES = ["Qualification", "Needs Analysis", "Proposal", "Closed Won"]
STAGE_PROBABILITY = {
    "Qualification": 10.0,
    "Needs Analysis": 25.0,
    "Proposal": 50.0,
    "Closed Won": 100.0,
}
ACTIVITY_TYPES = ["Call", "Meeting", "Task"]


def _phone(rng: random.Random, used: set[str]) -> str:
    while True:
        candidate = f"+919000{rng.randrange(100000, 1000000):06d}"
        if candidate not in used:
            used.add(candidate)
            return candidate


def _write_csv(path: Path, header: list[str], rows: list[list[str]], blank_after: int = -1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Fixed LF + explicit terminator: csv defaults to CRLF and text mode
    # follows the platform, either of which would break byte-determinism.
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        for index, row in enumerate(rows):
            writer.writerow(row)
            if index == blank_after:
                handle.write("\n")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def build(rng: random.Random) -> dict[str, list[list[str]]]:
    """Generate all rows; return the named tables (defects injected inline)."""
    used_phones: set[str] = set()
    persons: list[list[str]] = []
    for i in range(1, N_PERSONS + 1):
        persons.append(
            [
                str(i),
                f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                f"person{i:04d}@example.invalid",
                _phone(rng, used_phones),
                str((i % N_ORGANIZATIONS) + 1),
                rng.choice(["web", "referral"]),
                ACTIVE_OWNER,
                f"2026-01-{(i % 28) + 1:02d}",
            ]
        )
    # Seeded person defects (indices are 0-based into the table above).
    persons[10] = ["911", "Short"]  # wrong_column_count
    persons[30][2] = "dup.person@example.invalid"
    persons[31][2] = "DUP.PERSON@example.invalid"
    persons[31][3] = _phone(rng, used_phones)
    persons[30][7] = "2026-01-05"
    persons[31][7] = "2026-01-06"
    persons[40][2] = "not-an-email"
    persons[41][1] = "N" * 81
    persons[42][3] = "zzz"
    persons[50][0] = "9001"
    persons[51][0] = "9001"
    persons[51][2] = "external.dup@example.invalid"
    persons[51][3] = _phone(rng, used_phones)
    persons[60][6] = INACTIVE_OWNER
    persons[61][6] = UNKNOWN_OWNER
    persons[62][5] = "pigeon"
    persons[70][2] = RETURNING_EMAIL
    persons[71][1] = ""

    organizations: list[list[str]] = []
    combos = [(city, trade) for city in CITIES for trade in TRADES]
    rng.shuffle(combos)
    closers = [(adj, noun) for adj in CLOSER_ADJECTIVES for noun in CLOSER_NOUNS]
    rng.shuffle(closers)
    for i in range(1, N_ORGANIZATIONS + 1):
        city, trade = combos[i - 1]
        adj, noun = closers[i - 1]
        organizations.append(
            [str(i), f"{city} {trade} {adj} {noun}", "India", f"2026-01-{(i % 28) + 1:02d}"]
        )
    organizations[5] = ["501", "Marigold Labs Private Limited", "India", "2026-01-03"]
    organizations[6] = ["502", "Marigold Labs Private Ltd", "India", "2026-01-04"]
    organizations[7] = ["503", "", "India", "2026-01-05"]

    deals: list[list[str]] = []
    for i in range(1, N_DEALS + 1):
        stage = STAGES[i % len(STAGES)]
        value = f"{(i * 137) % 90000 + 1000}.00"
        day = (i % 27) + 1
        deals.append(
            [
                str(i),
                f"Deal {i:04d} expansion",
                str((i % N_PERSONS) + 1),
                str((i % N_ORGANIZATIONS) + 1),
                value,
                "INR" if i % 3 else "USD",
                stage,
                "open",
                f"{day:02d}/02/2026",
                str(int(STAGE_PROBABILITY[stage])),
            ]
        )
    deals[100][6] = "Warp Drive"
    deals[101][6] = "Qualification"
    deals[101][9] = "80"
    deals[102][4] = "1.234"
    deals[103][5] = "XX"
    deals[104][8] = "someday"

    activities: list[list[str]] = []
    for i in range(1, N_ACTIVITIES + 1):
        activities.append(
            [
                str(i),
                f"Follow-up {i}",
                str((i % N_DEALS) + 1),
                ACTIVITY_TYPES[i % len(ACTIVITY_TYPES)],
                f"2026-02-{(i % 27) + 1:02d}",
                f"2026-01-{(i % 28) + 1:02d}",
            ]
        )
    for index in (11, 55, 150):
        activities[index][3] = "Fax"

    return {
        "persons": persons,
        "organizations": organizations,
        "deals": deals,
        "activities": activities,
    }


MAPPING = """version: 1
source: pipedrive
entities:
  - name: people
    source_kind: persons
    target_module: Contacts
    fields:
      Last_Name: {from: Name, transform: [trim], required: true}
      Email: {from: Email, transform: [trim, casefold], pii: true}
      Phone: {from: Phone, transform: [trim, e164(region=IN)]}
      Lead_Source:
        {from: Source, transform: [{map: {values: {web: Web, referral: Referral, pigeon: Pigeon}}}]}
      Owner: {from: OwnerEmail}
      id: {from: ID}
      Nickname: {from: Nickname}
      Mystery: {from: Source}
    external_id: {field: External_ID__s, from: ID}
  - name: companies
    source_kind: organizations
    target_module: Accounts
    fields:
      Account_Name: {from: Name, transform: [trim], required: true}
    external_id: {field: External_ID__s, from: ID}
  - name: deals
    source_kind: deals
    target_module: Deals
    fields:
      Deal_Name: {from: Title, transform: [trim], required: true}
      Amount: {from: Value, transform: [money(currency_col=Currency)]}
      Stage: {from: Stage, transform: [trim], required: true}
      Closing_Date: {from: Expected_Close, transform: [date(format="%d/%m/%Y")]}
      Probability: {from: Prob}
      Account_Name: {from: Organization ID}
    external_id: {field: External_ID__s, from: ID}
    stage_probabilities:
      {Qualification: 10.0, Needs Analysis: 25.0, Proposal: 50.0, Closed Won: 100.0}
  - name: activities
    source_kind: activities
    target_module: Calls
    fields:
      Subject: {from: Subject, transform: [trim], required: true}
    external_id: {field: External_ID__s, from: ID}
    lookups:
      Call_For: {entity: deals, via: Deal ID}
    history: {type_col: Type, supported: [Call, Meeting, Task]}
"""

PERSONS_HEADER = [
    "ID",
    "Name",
    "Email",
    "Phone",
    "Organization ID",
    "Source",
    "OwnerEmail",
    "Created",
]
ORGANIZATIONS_HEADER = ["ID", "Name", "Country", "Created"]
DEALS_HEADER = [
    "ID",
    "Title",
    "Person ID",
    "Organization ID",
    "Value",
    "Currency",
    "Stage",
    "Status",
    "Expected_Close",
    "Prob",
]
ACTIVITIES_HEADER = ["ID", "Subject", "Deal ID", "Type", "Due date", "Created"]


def _field(api_name: str, data_type: str, **extra: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "api_name": api_name,
        "data_type": data_type,
        "field_label": api_name,
        "json_type": "string",
        "length": 120,
        "pick_list_values": [],
        "read_only": False,
        "system_mandatory": False,
    }
    entry.update(extra)
    return entry


def metadata() -> dict[str, object]:
    """Marigold target metadata (mirrors the real fields shape)."""
    return {
        "Contacts": [
            _field("Last_Name", "text", length=80, system_mandatory=True),
            _field("Email", "email", length=100),
            _field("Phone", "phone", length=30),
            _field(
                "Lead_Source",
                "picklist",
                pick_list_values=[
                    {"actual_value": "Web"},
                    {"actual_value": "Referral"},
                    {"actual_value": "Partner"},
                ],
            ),
            _field("Owner", "ownerlookup"),
            _field("id", "bigint", length=18, read_only=True),
            _field("Nickname", "text", length=50),
            _field("External_ID__s", "text", length=50, unique=True),
        ],
        "Accounts": [
            _field("Account_Name", "text", length=200, system_mandatory=True),
            _field("External_ID__s", "text", length=50, unique=True),
            _field("id", "bigint", length=18, read_only=True),
        ],
        "Deals": [
            _field("Deal_Name", "text", length=120, system_mandatory=True),
            _field("Amount", "currency", length=16),
            _field(
                "Stage",
                "picklist",
                pick_list_values=[{"actual_value": s} for s in STAGES],
                system_mandatory=True,
            ),
            _field("Closing_Date", "date", length=20),
            _field("Probability", "double", length=16),
            _field(
                "Pipeline",
                "picklist",
                pick_list_values=[{"actual_value": "Standard"}, {"actual_value": "Enterprise"}],
                system_mandatory=True,
            ),
            _field("Account_Name", "lookup", lookup={"module": {"api_name": "Accounts"}}),
            _field("External_ID__s", "text", length=50, unique=True),
            _field("id", "bigint", length=18, read_only=True),
        ],
        "Calls": [
            _field("Subject", "text", length=200, system_mandatory=True),
            _field("External_ID__s", "text", length=50, unique=True),
            _field("id", "bigint", length=18, read_only=True),
        ],
    }


EXPECTED_MD = """# Marigold migration answer key (expected findings)

Seeded defects in the synthetic Pipedrive-shaped export and the finding
code that must catch each one. Numbers are 1-based physical file lines
(the header is line 1): every per-record finding carries its line in
evidence and keys on the stable source record ID (never a position).
Only `row_parse_error` is positional (a parse fault has no record to
key on). The CI test asserts exact set equality between the detected
(entity, code, source_id, line, severity) tuples and `answer_key.json`,
with zero unexpected error-severity findings.

## Persons (800 data rows + 1 blank line)

| # | Defect | Expected code |
|---|---|---|
| 1 | Line 12 has 2 cells (header needs 8) | `row_parse_error` (error) |
| 2 | Line 23 is blank | `row_parse_error` (warning) |
| 3a | Lines 33+34 (IDs 31+32) share an email | `unique_field_collision_in_batch` x2 |
| 3b | Survivor of the pair is ID 31 | `fuzzy_duplicate_cluster` x1 |
| 4 | Line 43 (ID 41) email is not an address | `type_incompatible` (error) |
| 5 | Line 44 (ID 42) name is 81 chars (max 80) | `value_too_long` (error) |
| 6 | Line 45 (ID 43) phone cannot parse as E.164 | `type_incompatible` (error) |
| 7 | Lines 53+54 share external ID 9001 | `unique_field_collision_in_batch` x2 (error) |
| 8 | Line 63 (ID 61) owner is inactive | `inactive_owner` (error) |
| 9 | Line 64 (ID 62) owner matches no user | `owner_unmapped` (error) |
| 10 | Line 65 (ID 63) Pigeon is no picklist value | `picklist_value_missing` (error) |
| 11 | Line 73 (ID 71) email already exists in the target | `would_duplicate_existing` (review) |
| 12 | Line 74 (ID 72) name is empty (required) | `type_incompatible` (error) |
| 13a | Mapping targets Mystery (absent) | `unknown_target_field` x1 |
| 13b | Mapping writes id (read-only) | `read_only_target_field` x1 |
| 13c | Nickname column missing from header | `missing_source_column` x1 |

## Organizations (200 rows)

| # | Defect | Expected code |
|---|---|---|
| 14 | Lines 7+8 (IDs 501+502) are fuzzy duplicates | `fuzzy_duplicate_cluster` x1 (review) |
| 15 | Line 9 (ID 503) name is empty (required) | `type_incompatible` (error) |

## Deals (700 rows)

| # | Defect | Expected code |
|---|---|---|
| 16a | Line 102 (ID 101) stage Warp Drive is outside the picklist | `picklist_value_missing` x1 |
| 16b | Same row against the Deals pipeline | `unmapped_stage` x1 |
| 17 | Line 103 (ID 102) Qualification 80%, expects 10% | `stage_probability_mismatch` (warning) |
| 18 | Line 104 (ID 103) amount has 3 decimals | `type_incompatible` (error) |
| 19 | Line 105 (ID 104) currency XX is unknown | `type_incompatible` (error) |
| 20 | Line 106 (ID 105) close date cannot parse | `type_incompatible` (error) |
| 21 | Mandatory Pipeline has no mapping | `mandatory_field_unmapped` (error) |
| 22 | Account_Name lookup has no resolution | `lookup_unresolvable` (review) |

## Activities (300 rows)

| # | Defect | Expected code |
|---|---|---|
| 23 | Lines 13, 57, 152 (IDs 12, 56, 151) are Fax | `history_type_unsupported` x3 + x1 info |

## Coverage

Live-search coverage per entity: `target_dedupe_coverage` (info x4).
"""

#: Row-level answer key: one entry per expected finding. Per-record
#: entries carry the stable source record ID plus the 1-based physical
#: file line (header is line 1); `row_parse_error` entries carry only
#: the line (a parse fault has no record to key on); mapping-level,
#: cluster, coverage and counts entries carry the finding's entity_id
#: with no single line. The CI test asserts exact set equality between
#: these tuples and the detected findings.
ANSWER_KEY = [
    {
        "entity": "people",
        "code": "row_parse_error",
        "source_id": None,
        "line": 12,
        "severity": "error",
    },
    {
        "entity": "people",
        "code": "row_parse_error",
        "source_id": None,
        "line": 23,
        "severity": "warning",
    },
    {
        "entity": "people",
        "code": "unique_field_collision_in_batch",
        "source_id": "31",
        "line": 33,
        "severity": "error",
    },
    {
        "entity": "people",
        "code": "unique_field_collision_in_batch",
        "source_id": "32",
        "line": 34,
        "severity": "error",
    },
    {
        "entity": "people",
        "code": "fuzzy_duplicate_cluster",
        "source_id": "31",
        "line": None,
        "severity": "review",
    },
    {
        "entity": "people",
        "code": "type_incompatible",
        "source_id": "41",
        "line": 43,
        "severity": "error",
    },
    {
        "entity": "people",
        "code": "value_too_long",
        "source_id": "42",
        "line": 44,
        "severity": "error",
    },
    {
        "entity": "people",
        "code": "type_incompatible",
        "source_id": "43",
        "line": 45,
        "severity": "error",
    },
    {
        "entity": "people",
        "code": "unique_field_collision_in_batch",
        # Shared external ID 9001: the key carries a row-content suffix so
        # each colliding row keeps a distinct finding ID.
        "source_id": "9001#b50fdaec",
        "line": 53,
        "severity": "error",
    },
    {
        "entity": "people",
        "code": "unique_field_collision_in_batch",
        "source_id": "9001#4a7f2606",
        "line": 54,
        "severity": "error",
    },
    {
        "entity": "people",
        "code": "inactive_owner",
        "source_id": "61",
        "line": 63,
        "severity": "error",
    },
    {
        "entity": "people",
        "code": "owner_unmapped",
        "source_id": "62",
        "line": 64,
        "severity": "error",
    },
    {
        "entity": "people",
        "code": "picklist_value_missing",
        "source_id": "63",
        "line": 65,
        "severity": "error",
    },
    {
        "entity": "people",
        "code": "would_duplicate_existing",
        "source_id": "71",
        "line": 73,
        "severity": "review",
    },
    {
        "entity": "people",
        "code": "type_incompatible",
        "source_id": "72",
        "line": 74,
        "severity": "error",
    },
    {
        "entity": "people",
        "code": "unknown_target_field",
        "source_id": "Mystery",
        "line": None,
        "severity": "error",
    },
    {
        "entity": "people",
        "code": "read_only_target_field",
        "source_id": "id",
        "line": None,
        "severity": "error",
    },
    {
        "entity": "people",
        "code": "missing_source_column",
        "source_id": "Nickname",
        "line": None,
        "severity": "error",
    },
    {
        "entity": "people",
        "code": "target_dedupe_coverage",
        "source_id": "coverage",
        "line": None,
        "severity": "info",
    },
    {
        "entity": "companies",
        "code": "fuzzy_duplicate_cluster",
        "source_id": "501",
        "line": None,
        "severity": "review",
    },
    {
        "entity": "companies",
        "code": "type_incompatible",
        "source_id": "503",
        "line": 9,
        "severity": "error",
    },
    {
        "entity": "companies",
        "code": "target_dedupe_coverage",
        "source_id": "coverage",
        "line": None,
        "severity": "info",
    },
    {
        "entity": "deals",
        "code": "picklist_value_missing",
        "source_id": "101",
        "line": 102,
        "severity": "error",
    },
    {
        "entity": "deals",
        "code": "unmapped_stage",
        "source_id": "101",
        "line": 102,
        "severity": "error",
    },
    {
        "entity": "deals",
        "code": "stage_probability_mismatch",
        "source_id": "102",
        "line": 103,
        "severity": "warning",
    },
    {
        "entity": "deals",
        "code": "type_incompatible",
        "source_id": "103",
        "line": 104,
        "severity": "error",
    },
    {
        "entity": "deals",
        "code": "type_incompatible",
        "source_id": "104",
        "line": 105,
        "severity": "error",
    },
    {
        "entity": "deals",
        "code": "type_incompatible",
        "source_id": "105",
        "line": 106,
        "severity": "error",
    },
    {
        "entity": "deals",
        "code": "mandatory_field_unmapped",
        "source_id": "Pipeline",
        "line": None,
        "severity": "error",
    },
    {
        "entity": "deals",
        "code": "lookup_unresolvable",
        "source_id": "Account_Name",
        "line": None,
        "severity": "review",
    },
    {
        "entity": "deals",
        "code": "target_dedupe_coverage",
        "source_id": "coverage",
        "line": None,
        "severity": "info",
    },
    {
        "entity": "activities",
        "code": "history_type_unsupported",
        "source_id": "12",
        "line": 13,
        "severity": "warning",
    },
    {
        "entity": "activities",
        "code": "history_type_unsupported",
        "source_id": "56",
        "line": 57,
        "severity": "warning",
    },
    {
        "entity": "activities",
        "code": "history_type_unsupported",
        "source_id": "151",
        "line": 152,
        "severity": "warning",
    },
    {
        "entity": "activities",
        "code": "history_type_unsupported",
        "source_id": "counts",
        "line": None,
        "severity": "info",
    },
    {
        "entity": "activities",
        "code": "target_dedupe_coverage",
        "source_id": "coverage",
        "line": None,
        "severity": "info",
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the Marigold migration fixtures.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output directory.")
    args = parser.parse_args()
    out = Path(args.out)
    rng = random.Random(SEED)
    tables = build(rng)
    source = out / "source"
    _write_csv(source / "persons.csv", PERSONS_HEADER, tables["persons"], blank_after=20)
    _write_csv(source / "organizations.csv", ORGANIZATIONS_HEADER, tables["organizations"])
    _write_csv(source / "deals.csv", DEALS_HEADER, tables["deals"])
    _write_csv(source / "activities.csv", ACTIVITIES_HEADER, tables["activities"])
    _write_text(out / "mapping.yaml", MAPPING)
    for module, fields in metadata().items():
        _write_json(out / "fields" / f"fields_{module}.json", {"fields": fields})
    _write_json(
        out / "users.json",
        {
            "users": [
                {"email": ACTIVE_OWNER, "status": "active"},
                {"email": INACTIVE_OWNER, "status": "inactive"},
            ]
        },
    )
    _write_json(
        out / "target_existing.json",
        {
            "Contacts": [
                {"id": f"1455423000000{i:05d}", "Email": email}
                for i, email in enumerate(
                    [
                        RETURNING_EMAIL,
                        "customer.a@example.invalid",
                        "customer.b@example.invalid",
                        "customer.c@example.invalid",
                        "customer.d@example.invalid",
                    ]
                )
            ]
        },
    )
    _write_text(out / "EXPECTED.md", EXPECTED_MD)
    _write_json(out / "answer_key.json", {"seed": SEED, "expected": ANSWER_KEY})
    total = sum(len(tables[key]) for key in ("persons", "organizations", "deals", "activities"))
    print(f"wrote {total} rows to {out}")


if __name__ == "__main__":
    main()
