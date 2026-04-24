Multi-project orchestration scaffolding (Model A):
- All core tables now have project_id column and are indexed by project_id
- A new projects registry (projects) contains a catalog of projects
- Default project_id is default; you can set OC_PROJECT_ID to switch context
