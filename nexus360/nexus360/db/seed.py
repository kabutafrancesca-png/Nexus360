"""Seed demo data into whichever database is configured.

Works with both Postgres (Supabase) and local SQLite.
Run AFTER the schema has been applied:
    python db/seed.py

Demo logins — password for all accounts: nexus123
    admin@infratel.test
    manager@infratel.test
    am@infratel.test
    rep@infratel.test
    exec@infratel.test
"""
import os, sys, random, sqlite3, re, uuid
from datetime import date, timedelta, datetime

# Make sure the project root is on the path so config.py is importable
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()

# ── Resolve DATABASE_URL (same logic as config.py) ───────────────────────────
_LOCAL_DB   = os.path.join(_HERE, "nexus360_local.sqlite3")
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{_LOCAL_DB}"
IS_SQLITE    = DATABASE_URL.startswith("sqlite")

# ── Connect ───────────────────────────────────────────────────────────────────
if IS_SQLITE:
    _path = re.sub(r"^sqlite:///", "", DATABASE_URL)
    conn  = sqlite3.connect(_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    PH = "?"          # placeholder style
else:
    import psycopg2
    conn = psycopg2.connect(DATABASE_URL)
    PH = "%s"


# ── Thin helpers ──────────────────────────────────────────────────────────────
def ph(sql: str) -> str:
    """Swap ? for %s when talking to Postgres."""
    return sql if IS_SQLITE else sql.replace("?", "%s")


def run(sql: str, params=()):
    cur = conn.cursor()
    cur.execute(ph(sql), params)
    return cur


def fetchone(sql: str, params=()):
    cur = run(sql, params)
    row = cur.fetchone()
    return dict(row) if row else None


def uid() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def date_iso(d: date) -> str:
    return d.isoformat()


# ── Seed ──────────────────────────────────────────────────────────────────────
pw = generate_password_hash("nexus123")

print("Seeding users …")
users = [
    (uid(), "admin@infratel.test",   "System Admin",             "admin"),
    (uid(), "manager@infratel.test", "Mwansa Sales-Manager",     "sales_manager"),
    (uid(), "am@infratel.test",      "Chanda Account-Manager",   "account_manager"),
    (uid(), "rep@infratel.test",     "Temwani Sales-Rep",        "sales_rep"),
    (uid(), "exec@infratel.test",    "Exec Sponsor",             "executive"),
]
for user_id, email, full_name, role in users:
    run("""INSERT OR IGNORE INTO users (id, email, password_hash, full_name, role)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, email, pw, full_name, role))

am_row = fetchone("SELECT id FROM users WHERE email = ?", ("am@infratel.test",))
am_id  = am_row["id"]

print("Seeding verticals and products …")
verticals = [
    "Telecommunications", "Mining", "Banking & Fintech",
    "Government & Public Sector", "Retail & FMCG", "Healthcare",
]
for v in verticals:
    run("INSERT OR IGNORE INTO verticals (name) VALUES (?)", (v,))

products = [
    ("Colocation",                "Data Centre"),
    ("Cloud Compute",             "Cloud"),
    ("Internet Connectivity",     "Network"),
    ("Disaster Recovery (DRaaS)", "Cloud"),
    ("SD-WAN",                    "Network"),
    ("Managed Backup",            "Cloud"),
]
for name, category in products:
    run("INSERT OR IGNORE INTO products (name, category) VALUES (?, ?)", (name, category))

vert_rows = conn.execute("SELECT id FROM verticals ORDER BY id").fetchall()
vids = [r[0] for r in vert_rows]

print("Seeding accounts, contacts, opportunities and contracts …")
company_names = [
    "Zamtel Demo Ltd", "Kansanshi Demo Mining", "Zanaco Demo Bank",
    "MoH Demo Dept",   "Shoprite Demo",         "Airtel Demo",
    "FQM Demo",        "Stanbic Demo",
]
tiers    = ["standard", "strategic", "key"]
statuses = ["active", "active", "at_risk", "renewal_due"]
regions  = ["Lusaka", "Copperbelt", "Southern"]
stages   = ["qualification", "proposal", "negotiation"]
maturities = ["bronze", "silver", "gold", "platinum"]
win_probs  = [15.0, 40.0, 70.0, 90.0]

for i, company in enumerate(company_names):
    acc_id = uid()
    contracted = random.randint(50, 900) * 1000
    run("""INSERT OR IGNORE INTO accounts
             (id, company_name, vertical_id, tier, region,
              contracted_revenue, status, health_score, owner_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (acc_id, company, vids[i % len(vids)],
         random.choice(tiers), random.choice(regions),
         contracted, random.choice(statuses),
         random.randint(40, 95), am_id))

    # Three contacts per account (buying committee)
    for role in ["economic_buyer", "technical_evaluator", "champion"]:
        run("""INSERT INTO contacts
                 (id, account_id, full_name, job_title, email, decision_role)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (uid(), acc_id,
             f"{role.replace('_',' ').title()} @ {company}",
             role.replace("_", " ").title(),
             f"{role}@{company.split()[0].lower()}.test",
             role))

    # One open opportunity per account
    maturity    = random.choice(maturities)
    win_prob    = random.choice(win_probs)
    amount      = random.randint(20, 500) * 1000
    weighted    = round(amount * win_prob / 100, 2)
    close_date  = date_iso(date.today() + timedelta(days=random.randint(15, 120)))
    run("""INSERT INTO opportunities
             (id, account_id, name, stage, maturity, maturity_score,
              win_probability, amount, weighted_amount, expected_close, owner_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (uid(), acc_id, f"{company} - expansion",
         random.choice(stages), maturity, random.randint(10, 90),
         win_prob, amount, weighted, close_date, am_id))

    # One active contract per account
    effective = date_iso(date.today() - timedelta(days=300))
    expiry    = date_iso(date.today() + timedelta(days=random.choice([25, 55, 85, 170, 300])))
    run("""INSERT INTO contracts
             (id, account_id, title, type, status,
              effective_date, expiry_date, annual_value, contract_number)
           VALUES (?, ?, ?, 'msa', 'active', ?, ?, ?, ?)""",
        (uid(), acc_id, f"MSA - {company}",
         effective, expiry,
         random.randint(50, 900) * 1000,
         f"NX-{1000 + i}"))

conn.commit()
conn.close()
print(f"Done — seeded {len(company_names)} accounts.")
print("Login: admin@infratel.test / nexus123")
