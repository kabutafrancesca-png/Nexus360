"""Seed demo data (so everyone's pages have something to show).
Run:  python db/seed.py      (after running db/schema.sql)
Demo logins -> password for all: nexus123
  admin@infratel.test | manager@infratel.test | am@infratel.test | rep@infratel.test | exec@infratel.test
"""
import os, sys, random
from datetime import date, timedelta
import psycopg2
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()
conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()
pw = generate_password_hash("nexus123")

users = [
    ("admin@infratel.test", "System Admin", "admin"),
    ("manager@infratel.test", "Mwansa Sales-Manager", "sales_manager"),
    ("am@infratel.test", "Chanda Account-Manager", "account_manager"),
    ("rep@infratel.test", "Temwani Sales-Rep", "sales_rep"),
    ("exec@infratel.test", "Exec Sponsor", "executive"),
]
for e, n, r in users:
    cur.execute("INSERT INTO users (email,password_hash,full_name,role) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING", (e, pw, n, r))
cur.execute("SELECT id FROM users WHERE email='am@infratel.test'"); am = cur.fetchone()[0]

for v in ["Telecommunications", "Mining", "Banking & Fintech", "Government & Public Sector", "Retail & FMCG", "Healthcare"]:
    cur.execute("INSERT INTO verticals (name) VALUES (%s) ON CONFLICT DO NOTHING", (v,))
for p, c in [("Colocation","Data Centre"),("Cloud Compute","Cloud"),("Internet Connectivity","Network"),
             ("Disaster Recovery (DRaaS)","Cloud"),("SD-WAN","Network"),("Managed Backup","Cloud")]:
    cur.execute("INSERT INTO products (name,category) VALUES (%s,%s) ON CONFLICT DO NOTHING", (p, c))

cur.execute("SELECT id FROM verticals ORDER BY id"); vids = [r[0] for r in cur.fetchall()]
names = ["Zamtel Demo Ltd","Kansanshi Demo Mining","Zanaco Demo Bank","MoH Demo Dept","Shoprite Demo","Airtel Demo","FQM Demo","Stanbic Demo"]
for i, n in enumerate(names):
    cur.execute("""INSERT INTO accounts (company_name,vertical_id,tier,region,contracted_revenue,status,health_score,owner_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (n, vids[i % len(vids)], random.choice(["standard","strategic","key"]), random.choice(["Lusaka","Copperbelt","Southern"]),
                 random.randint(50, 900) * 1000, random.choice(["active","active","at_risk","renewal_due"]), random.randint(40, 95), am))
    aid = cur.fetchone()[0]
    for role in ["economic_buyer", "technical_evaluator", "champion"]:
        cur.execute("INSERT INTO contacts (account_id,full_name,job_title,email,decision_role) VALUES (%s,%s,%s,%s,%s)",
                    (aid, f"{role.title()} @ {n}", role.replace("_"," ").title(), f"{role}@{n.split()[0].lower()}.test", role))
    cur.execute("""INSERT INTO opportunities (account_id,name,stage,maturity,maturity_score,win_probability,amount,expected_close,owner_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (aid, f"{n} - expansion", random.choice(["qualification","proposal","negotiation"]),
                 random.choice(["bronze","silver","gold","platinum"]), random.randint(10, 90), random.choice([15, 40, 70, 90]),
                 random.randint(20, 500) * 1000, date.today() + timedelta(days=random.randint(15, 120)), am))
    cur.execute("""INSERT INTO contracts (account_id,title,type,status,effective_date,expiry_date,annual_value,contract_number)
                   VALUES (%s,%s,'msa','active',%s,%s,%s,%s)""",
                (aid, f"MSA - {n}", date.today() - timedelta(days=300), date.today() + timedelta(days=random.choice([25, 55, 85, 170, 300])),
                 random.randint(50, 900) * 1000, f"NX-{1000+i}"))
conn.commit()
print("Seeded. Login: admin@infratel.test / nexus123")
