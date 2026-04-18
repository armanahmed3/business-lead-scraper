"""
Compatibility bridge for AI Email Generator.
"""
import streamlit as st
import os
import sys

# Ensure parent dir is in path for imports
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
try:
    from ai_manager import query_ai_model
except ImportError:
    def query_ai_model(prompt, **kwargs):
        return {"content": "AI Service currently unavailable. Please check your API keys."}

class AIEmailGenerator:
    def generate_email(self, lead, tone, api_key=None):
        prompt = f"Write a {tone} cold email to {lead.get('name', 'Prospect')} who works at {lead.get('company', 'their company')}. Their job title is {lead.get('title', 'Professional')}."
        
        response = query_ai_model(prompt)
        
        if "error" in response:
            return {
                "subject": f"Follow up for {lead.get('company')}",
                "body": f"Hello {lead.get('name')},\n\nI'm reaching out from the team..."
            }
            
        content = response.get("content", "")
        # Very simple parser for subject/body
        if "Subject:" in content:
            parts = content.split("Subject:", 1)[1].split("\n", 1)
            subject = parts[0].strip()
            body = parts[1].strip() if len(parts) > 1 else content
        else:
            subject = f"Hello from our team"
            body = content
            
        return {"subject": subject, "body": body}

# Instance for the UI
ai_email_generator = AIEmailGenerator()
