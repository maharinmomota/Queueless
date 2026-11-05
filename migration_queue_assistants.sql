USE queueless;

-- Run once on an existing Queueless database. MySQL 8.0.29+ supports IF NOT EXISTS here.
ALTER TABLE users ADD COLUMN IF NOT EXISTS assigned_doctor_id INT NULL;

-- Create a separate login for each doctor's assistant. Password for all demo assistants: ChangeMe123!
-- Run create_admins.py after this migration to create the accounts.
