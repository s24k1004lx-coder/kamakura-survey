"""DB cleanup script"""
import toml
from supabase import create_client

s = toml.load(".streamlit/secrets.toml")
c = create_client(s["supabase"]["url"], s["supabase"]["key"])
nil = "00000000-0000-0000-0000-000000000000"
c.table("answers").delete().neq("id", nil).execute()
c.table("classifications").delete().neq("id", nil).execute()
c.table("edit_history").delete().neq("id", nil).execute()
c.table("responses").delete().neq("id", nil).execute()
c.table("survey_groups").delete().neq("id", nil).execute()
print("All test data deleted.")
