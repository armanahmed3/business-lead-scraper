"""
Compatibility bridge for Email Scheduler.
"""
import os
import json
from datetime import datetime

class EmailScheduler:
    def __init__(self):
        self.schedule_file = os.path.join(os.path.dirname(__file__), "scheduled_emails.json")

    def schedule_campaign(self, campaign_name, recipients, subject, body, send_time, delay_seconds):
        try:
            with open(self.schedule_file, 'r') as f:
                scheduled = json.load(f)
        except:
            scheduled = []
            
        campaign_id = f"sched_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        new_entry = {
            "campaign_id": campaign_id,
            "name": campaign_name,
            "recipients_count": len(recipients),
            "scheduled_for": send_time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "scheduled"
        }
        
        scheduled.append(new_entry)
        with open(self.schedule_file, 'w') as f:
            json.dump(scheduled, f)
            
        return campaign_id

# Instance for UI
email_scheduler = EmailScheduler()
