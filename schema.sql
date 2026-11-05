CREATE DATABASE IF NOT EXISTS queueless CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE queueless;

CREATE TABLE IF NOT EXISTS users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  full_name VARCHAR(120) NOT NULL,
  email VARCHAR(190) NOT NULL UNIQUE,
  phone VARCHAR(30) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  role ENUM('app_admin','hospital_admin','queue_manager','patient') NOT NULL DEFAULT 'patient',
  assigned_doctor_id INT NULL,
  date_of_birth DATE NULL,
  gender VARCHAR(30) NULL,
  address VARCHAR(255) NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS doctors (
  id INT AUTO_INCREMENT PRIMARY KEY,
  full_name VARCHAR(120) NOT NULL,
  speciality VARCHAR(100) NOT NULL,
  qualification VARCHAR(180) NULL,
  bio TEXT NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  queue_status ENUM('open','paused','closed') NOT NULL DEFAULT 'open',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS doctor_schedules (
  id INT AUTO_INCREMENT PRIMARY KEY,
  doctor_id INT NOT NULL,
  day_of_week TINYINT NOT NULL COMMENT '0=Monday, 6=Sunday',
  start_time TIME NOT NULL,
  end_time TIME NOT NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  CONSTRAINT fk_schedule_doctor FOREIGN KEY (doctor_id) REFERENCES doctors(id) ON DELETE CASCADE
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS assigned_doctor_id INT NULL;

CREATE TABLE IF NOT EXISTS symptoms (
  id INT AUTO_INCREMENT PRIMARY KEY,
  label VARCHAR(120) NOT NULL,
  category VARCHAR(80) NOT NULL,
  recommended_speciality VARCHAR(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS bookings (
  id INT AUTO_INCREMENT PRIMARY KEY,
  patient_id INT NOT NULL,
  doctor_id INT NOT NULL,
  visit_date DATE NOT NULL,
  queue_number INT NOT NULL,
  status ENUM('waiting','in_progress','paused','completed','cancelled') NOT NULL DEFAULT 'waiting',
  patient_notes TEXT NULL,
  symptom_summary TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_booking_patient FOREIGN KEY (patient_id) REFERENCES users(id),
  CONSTRAINT fk_booking_doctor FOREIGN KEY (doctor_id) REFERENCES doctors(id),
  UNIQUE KEY uq_doctor_date_queue (doctor_id, visit_date, queue_number)
);

-- Idempotent doctor seed: importing this schema more than once will not
-- create another copy of the same doctor.
INSERT INTO doctors (full_name,speciality,qualification,bio)
SELECT v.full_name,v.speciality,v.qualification,v.bio
FROM (
  SELECT 'Dr. Farhana Rahman' AS full_name,'General Physician' AS speciality,'MBBS, FCPS (Medicine)' AS qualification,'Primary care for common illnesses and general health concerns.' AS bio
  UNION ALL SELECT 'Dr. Mahmud Hasan','Cardiologist','MBBS, MD (Cardiology)','Heart health, chest discomfort and cardiovascular risk assessment.'
  UNION ALL SELECT 'Dr. Nusrat Jahan','Dermatologist','MBBS, DDV','Skin, hair and nail conditions.'
  UNION ALL SELECT 'Dr. Arif Chowdhury','Orthopedic Specialist','MBBS, MS (Orthopedics)','Bone, joint, muscle and injury assessment.'
  UNION ALL SELECT 'Dr. Samia Karim','Pediatrician','MBBS, FCPS (Pediatrics)','Health care for infants, children and adolescents.'
  UNION ALL SELECT 'Dr. Tanvir Ahmed','ENT Specialist','MBBS, FCPS (ENT)','Ear, nose and throat conditions.'
  UNION ALL SELECT 'Dr. Rukaiya Islam','Neurologist','MBBS, MD (Neurology)','Headache, dizziness, nerve and neurological concerns.'
  UNION ALL SELECT 'Dr. Imran Kabir','Gynecologist','MBBS, FCPS (OBGYN)','Women’s reproductive and maternal health.'
) AS v
WHERE NOT EXISTS (
  SELECT 1 FROM doctors d
  WHERE LOWER(TRIM(d.full_name))=LOWER(TRIM(v.full_name))
    AND LOWER(TRIM(d.speciality))=LOWER(TRIM(v.speciality))
);

-- Add each sample weekly schedule only if that exact schedule is not present.
INSERT INTO doctor_schedules (doctor_id,day_of_week,start_time,end_time)
SELECT d.id, v.day_of_week, v.start_time, v.end_time
FROM (
  SELECT 'Dr. Farhana Rahman' AS full_name,0 AS day_of_week,'09:00' AS start_time,'13:00' AS end_time
  UNION ALL SELECT 'Dr. Farhana Rahman',1,'09:00','13:00'
  UNION ALL SELECT 'Dr. Farhana Rahman',2,'09:00','13:00'
  UNION ALL SELECT 'Dr. Farhana Rahman',3,'09:00','13:00'
  UNION ALL SELECT 'Dr. Farhana Rahman',4,'09:00','13:00'
  UNION ALL SELECT 'Dr. Mahmud Hasan',0,'16:00','20:00'
  UNION ALL SELECT 'Dr. Mahmud Hasan',2,'16:00','20:00'
  UNION ALL SELECT 'Dr. Mahmud Hasan',4,'16:00','20:00'
  UNION ALL SELECT 'Dr. Nusrat Jahan',1,'15:00','19:00'
  UNION ALL SELECT 'Dr. Nusrat Jahan',3,'15:00','19:00'
  UNION ALL SELECT 'Dr. Nusrat Jahan',5,'10:00','13:00'
  UNION ALL SELECT 'Dr. Arif Chowdhury',0,'15:00','19:00'
  UNION ALL SELECT 'Dr. Arif Chowdhury',2,'15:00','19:00'
  UNION ALL SELECT 'Dr. Arif Chowdhury',5,'10:00','14:00'
  UNION ALL SELECT 'Dr. Samia Karim',0,'10:00','14:00'
  UNION ALL SELECT 'Dr. Samia Karim',1,'10:00','14:00'
  UNION ALL SELECT 'Dr. Samia Karim',3,'10:00','14:00'
  UNION ALL SELECT 'Dr. Tanvir Ahmed',1,'16:00','19:00'
  UNION ALL SELECT 'Dr. Tanvir Ahmed',4,'16:00','19:00'
  UNION ALL SELECT 'Dr. Rukaiya Islam',2,'15:00','19:00'
  UNION ALL SELECT 'Dr. Rukaiya Islam',5,'10:00','13:00'
  UNION ALL SELECT 'Dr. Imran Kabir',0,'15:00','18:00'
  UNION ALL SELECT 'Dr. Imran Kabir',3,'15:00','18:00'
) AS v
JOIN doctors d ON LOWER(TRIM(d.full_name))=LOWER(TRIM(v.full_name))
WHERE NOT EXISTS (
  SELECT 1 FROM doctor_schedules s
  WHERE s.doctor_id=d.id AND s.day_of_week=v.day_of_week
    AND s.start_time=v.start_time AND s.end_time=v.end_time
);

INSERT INTO symptoms (label,category,recommended_speciality) VALUES
('Fever','General','General Physician'),('Cough or cold','Respiratory','General Physician'),
('Weakness or fatigue','General','General Physician'),('Stomach discomfort','Digestive','General Physician'),
('Chest pain or pressure','Cardiac warning','Cardiologist'),('Palpitations','Cardiac','Cardiologist'),
('Skin rash or itching','Skin','Dermatologist'),('Hair loss','Skin','Dermatologist'),
('Joint pain','Musculoskeletal','Orthopedic Specialist'),('Back pain','Musculoskeletal','Orthopedic Specialist'),
('Child fever or illness','Child health','Pediatrician'),('Ear pain','ENT','ENT Specialist'),
('Sore throat','ENT','ENT Specialist'),('Frequent headaches','Neurological','Neurologist'),
('Dizziness or numbness','Neurological','Neurologist'),('Menstrual concerns','Women’s health','Gynecologist'),
('Pregnancy-related concern','Women’s health','Gynecologist');
