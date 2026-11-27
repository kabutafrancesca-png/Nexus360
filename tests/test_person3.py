"""End-to-end integration tests for Person 3 (WP2 Pipeline + WP3 Journey Tracker)."""
from datetime import datetime, timedelta, timezone
import os
import sys
import unittest
import uuid

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app import create_app
from app.db import execute, query_all, query_one
from app.modules.pipeline import service as pipeline_service


class Person3IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True

    def setUp(self):
        self.client = self.app.test_client()
        self.tag = f"P3TEST-{uuid.uuid4().hex[:8]}"
        self.created_account_ids = []
        self.created_lead_ids = []
        self.created_opp_ids = []
        self.created_event_ids = []
        self.created_task_ids = []
        self.created_notif_ids = []

    def tearDown(self):
        with self.app.app_context():
            for nid in self.created_notif_ids:
                execute("DELETE FROM notifications WHERE id = ?", (nid,))
            for tid in self.created_task_ids:
                execute("DELETE FROM tasks WHERE id = ?", (tid,))
            for eid in self.created_event_ids:
                execute("DELETE FROM tasks WHERE event_id = ?", (eid,))
                execute("DELETE FROM engagement_events WHERE id = ?", (eid,))
            for oid in self.created_opp_ids:
                execute("DELETE FROM opportunities WHERE id = ?", (oid,))
            for lid in self.created_lead_ids:
                execute("DELETE FROM leads WHERE id = ?", (lid,))
            for aid in self.created_account_ids:
                execute("DELETE FROM accounts WHERE id = ?", (aid,))
            execute(
                "DELETE FROM notifications WHERE title LIKE ? OR body LIKE ?",
                (f"%{self.tag}%", f"%{self.tag}%"),
            )
            execute("DELETE FROM audit_logs WHERE changes::text LIKE ?", (f"%{self.tag}%",))

    def _login(self, email="admin@infratel.test", password="nexus123"):
        self.client.get("/logout", follow_redirects=False)
        return self.client.post(
            "/login",
            data={"email": email, "password": password},
            follow_redirects=False,
        )

    def test_01_auth_guards_and_pages(self):
        r1 = self.client.get("/pipeline/", follow_redirects=False)
        r2 = self.client.get("/journey/", follow_redirects=False)
        self.assertEqual(r1.status_code, 302)
        self.assertIn("/login", r1.headers["Location"])
        self.assertEqual(r2.status_code, 302)
        self.assertIn("/login", r2.headers["Location"])

        self._login("admin@infratel.test")
        p = self.client.get("/pipeline/")
        j = self.client.get("/journey/")
        self.assertEqual(p.status_code, 200)
        self.assertIn(b"Kanban Board", p.data)
        self.assertEqual(j.status_code, 200)
        self.assertIn(b"Experiential Journey Tracker", j.data)

    def test_02_lead_crud_and_conversion(self):
        self._login("am@infratel.test")

        # Create lead
        res = self.client.post(
            "/pipeline/api/leads",
            json={
                "company_name": f"{self.tag} Copper Corp",
                "contact_name": f"{self.tag} Jane Phiri",
                "contact_email": "jane@copper.test",
                "source": "event",
                "status": "new",
                "score": 65,
            },
        )
        self.assertEqual(res.status_code, 201)
        lead = res.get_json()["data"]
        self.created_lead_ids.append(lead["id"])
        self.assertEqual(lead["status"], "new")

        # Update lead
        upd = self.client.put(
            f"/pipeline/api/leads/{lead['id']}",
            json={"status": "qualified", "score": 80},
        )
        self.assertEqual(upd.status_code, 200)
        self.assertEqual(upd.get_json()["data"]["status"], "qualified")

        # Convert lead -> account + contact + opportunity
        conv = self.client.post(
            f"/pipeline/api/leads/{lead['id']}/convert",
            json={
                "opportunity_name": f"{self.tag} Colocation Deal",
                "amount": 120000,
                "stage": "qualification",
                "tier": "strategic",
                "region": "Copperbelt",
            },
        )
        self.assertEqual(conv.status_code, 201)
        cdata = conv.get_json()["data"]
        self.created_account_ids.append(cdata["account"]["id"])
        self.created_opp_ids.append(cdata["opportunity"]["id"])
        self.assertTrue(cdata["created_account"])
        self.assertEqual(cdata["opportunity"]["maturity"], "bronze")
        self.assertGreater(cdata["opportunity"]["weighted_amount"], 0)

        with self.app.app_context():
            lrow = query_one("SELECT status, converted_account_id FROM leads WHERE id = ?", (lead["id"],))
            self.assertEqual(lrow["status"], "converted")
            self.assertEqual(str(lrow["converted_account_id"]), cdata["account"]["id"])

    def test_03_kanban_stage_move_and_dormancy_degradation(self):
        self._login("manager@infratel.test")

        with self.app.app_context():
            acc = query_one("SELECT id FROM accounts LIMIT 1")
            self.assertIsNotNone(acc)
            acc_id = str(acc["id"])

        # Create opportunity in qualification (Bronze)
        res = self.client.post(
            "/pipeline/api/opportunities",
            json={
                "account_id": acc_id,
                "name": f"{self.tag} SD-WAN Rollout",
                "stage": "qualification",
                "amount": 200000,
            },
        )
        self.assertEqual(res.status_code, 201)
        opp = res.get_json()["data"]
        self.created_opp_ids.append(opp["id"])
        self.assertEqual(opp["maturity"], "bronze")

        # Move to negotiation -> maturity should advance to gold
        mv = self.client.patch(
            f"/pipeline/api/opportunities/{opp['id']}/stage",
            json={"stage": "negotiation"},
        )
        self.assertEqual(mv.status_code, 200)
        moved = mv.get_json()["data"]
        self.assertEqual(moved["stage"], "negotiation")
        self.assertEqual(moved["maturity"], "gold")
        self.assertGreaterEqual(moved["win_probability"], 60)

        # Simulate dormancy (35 days ago -> -20 points -> drops from Gold 65 to Silver 45)
        old_ts = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat(timespec="seconds")
        with self.app.app_context():
            execute("UPDATE opportunities SET last_activity_at = ? WHERE id = ?", (old_ts, opp["id"]))

        dorm = self.client.post("/pipeline/api/dormancy/run", json={"dormant_days": 14})
        self.assertEqual(dorm.status_code, 200)
        ddata = dorm.get_json()["data"]
        self.assertGreaterEqual(ddata["degraded"], 1)

        with self.app.app_context():
            after = query_one("SELECT maturity, maturity_score FROM opportunities WHERE id = ?", (opp["id"],))
            self.assertEqual(after["maturity"], "silver")
            self.assertEqual(after["maturity_score"], 45)
            hist = query_all(
                "SELECT reason FROM opportunity_history WHERE opportunity_id = ? ORDER BY id DESC",
                (opp["id"],),
            )
            self.assertTrue(any("dormant" in (h["reason"] or "") for h in hist))

    def test_04_qualifying_dc_tour_triggers_maturity_task_and_notification(self):
        # Log in as account manager to run the DC tour
        self._login("am@infratel.test")

        with self.app.app_context():
            acc_id = str(uuid.uuid4())
            execute(
                """INSERT INTO accounts (id, company_name, tier, region, status)
                   VALUES (?, ?, 'strategic', 'Lusaka', 'active')""",
                (acc_id, f"{self.tag} Mining Holdings"),
            )
            self.created_account_ids.append(acc_id)

            contact_id = str(uuid.uuid4())
            execute(
                """INSERT INTO contacts (id, account_id, full_name, job_title, decision_role)
                   VALUES (?, ?, ?, 'CTO', 'economic_buyer')""",
                (contact_id, acc_id, f"{self.tag} Bwalya CTO"),
            )

            opp = pipeline_service.create_opportunity(
                account_id=acc_id,
                name=f"{self.tag} Colocation Deal",
                amount=150000,
                stage="qualification",
            )
            self.created_opp_ids.append(opp["id"])
            self.assertEqual(opp["maturity"], "bronze")

        # Log qualifying DC Tour
        res = self.client.post(
            "/journey/api/engagements",
            json={
                "account_id": acc_id,
                "opportunity_id": opp["id"],
                "type": "dc_tour",
                "title": f"{self.tag} Lusaka DC Tour",
                "attendee_ids": [contact_id],
                "outcome_notes": f"{self.tag} CTO impressed with Tier-III power redundancy",
                "follow_up_actions": "Send rack power quote within 24h",
            },
        )
        self.assertEqual(res.status_code, 201)
        payload = res.get_json()["data"]
        self.created_event_ids.append(payload["event"]["id"])
        if payload["trigger"]["task"]:
            self.created_task_ids.append(payload["trigger"]["task"]["id"])

        trig = payload["trigger"]
        self.assertTrue(trig["fired"])
        self.assertIsNotNone(trig["maturity_update"])
        self.assertEqual(trig["maturity_update"]["previous_maturity"], "bronze")
        self.assertEqual(trig["maturity_update"]["maturity"], "silver")
        self.assertGreaterEqual(trig["maturity_update"]["maturity_score"], 40)
        self.assertIsNotNone(trig["task"])
        self.assertEqual(trig["task"]["sla_hours"], 24)
        self.assertGreaterEqual(trig["notifications_sent"], 1)

        # Task lifecycle: open -> in_progress -> done
        task_id = trig["task"]["id"]
        t1 = self.client.patch(f"/journey/api/tasks/{task_id}", json={"status": "in_progress"})
        self.assertEqual(t1.status_code, 200)
        self.assertEqual(t1.get_json()["data"]["status"], "in_progress")

        t2 = self.client.patch(f"/journey/api/tasks/{task_id}", json={"status": "done"})
        self.assertEqual(t2.status_code, 200)
        self.assertEqual(t2.get_json()["data"]["status"], "done")
        self.assertIsNotNone(t2.get_json()["data"]["completed_at"])

        # Manager sees notification and marks it read
        self._login("manager@infratel.test")
        notifs = self.client.get("/journey/api/notifications").get_json()["data"]
        matching = [n for n in notifs["items"] if self.tag in (n.get("title") or "") or self.tag in (n.get("body") or "")]
        self.assertTrue(len(matching) >= 1)
        nid = matching[0]["id"]
        self.created_notif_ids.append(nid)

        rd = self.client.patch(f"/journey/api/notifications/{nid}/read", json={})
        self.assertEqual(rd.status_code, 200)
        self.assertTrue(rd.get_json()["data"]["is_read"])

        # Audit log written
        with self.app.app_context():
            aud = query_one(
                "SELECT id FROM audit_logs WHERE entity_type = 'engagement_event' AND entity_id = ?",
                (payload["event"]["id"],),
            )
            self.assertIsNotNone(aud)

    def test_05_rbac_and_analytics_endpoints(self):
        self._login("rep@infratel.test")
        # Sales rep cannot delete opportunities or run dormancy degradation
        r_del = self.client.delete(f"/pipeline/api/opportunities/{uuid.uuid4()}")
        self.assertEqual(r_del.status_code, 403)
        r_dorm = self.client.post("/pipeline/api/dormancy/run", json={})
        self.assertEqual(r_dorm.status_code, 403)

        # Analytics endpoints work cleanly
        pa = self.client.get("/pipeline/api/analytics")
        self.assertEqual(pa.status_code, 200)
        pdata = pa.get_json()["data"]
        self.assertIn("kpis", pdata)
        self.assertIn("by_stage", pdata)
        self.assertIn("by_maturity", pdata)

        ja = self.client.get("/journey/api/analytics")
        self.assertEqual(ja.status_code, 200)
        jdata = ja.get_json()["data"]
        self.assertIn("kpis", jdata)
        self.assertIn("by_type", jdata)
        self.assertIn("top_accounts", jdata)


if __name__ == "__main__":
    unittest.main(verbosity=2)
