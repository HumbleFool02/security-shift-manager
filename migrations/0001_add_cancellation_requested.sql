-- Adds cancellation-request tracking to the Absence table.
-- Applied manually to an existing MySQL database; a fresh db.create_all()
-- run already includes this column in the current Absence model.
ALTER TABLE absence ADD COLUMN cancellation_requested BOOLEAN NOT NULL DEFAULT FALSE;
