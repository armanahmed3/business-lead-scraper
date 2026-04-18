"""
Compatibility bridge for Lead Database.
Translates old UI calls to the new service-based architecture.
"""
import os
import pandas as pd
from datetime import datetime
import json

class LeadDatabase:
    def __init__(self):
        self.db_file = os.path.join(os.path.dirname(__file__), "leads_database.json")
        self._ensure_db()

    def _ensure_db(self):
        if not os.path.exists(self.db_file):
            with open(self.db_file, 'w') as f:
                json.dump([], f)

    def get_all_leads(self):
        try:
            with open(self.db_file, 'r') as f:
                return json.load(f)
        except:
            return []

    def get_hot_leads(self):
        return [l for l in self.get_all_leads() if l.get('score', 0) >= 80]

    def get_warm_leads(self):
        return [l for l in self.get_all_leads() if 60 <= l.get('score', 0) < 80]

    def get_cold_leads(self):
        return [l for l in self.get_all_leads() if l.get('score', 0) < 60]

    def get_all_categories(self):
        leads = self.get_all_leads()
        return list(set(l.get('category', 'Uncategorized') for l in leads))

    def get_leads_by_category(self, category):
        return [l for l in self.get_all_leads() if l.get('category') == category]

    def add_leads_bulk(self, leads_list):
        current_leads = self.get_all_leads()
        # Add ID if missing
        for i, lead in enumerate(leads_list):
            if 'id' not in lead:
                lead['id'] = len(current_leads) + i
        
        current_leads.extend(leads_list)
        with open(self.db_file, 'w') as f:
            json.dump(current_leads, f)
        return [l.get('id') for l in leads_list]

    def search_leads(self, query):
        leads = self.get_all_leads()
        if not query: return leads
        q = query.lower()
        return [l for l in leads if q in str(l.get('name', '')).lower() or q in str(l.get('email', '')).lower()]

    def export_leads(self, format='csv'):
        leads = self.get_all_leads()
        df = pd.DataFrame(leads)
        filename = f"exported_leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{format}"
        path = os.path.join(os.path.dirname(__file__), filename)
        if format == 'csv':
            df.to_csv(path, index=False)
        return path

# Instance for the UI
lead_db = LeadDatabase()
