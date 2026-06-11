-- Users table with additional fields for better personalization
CREATE TABLE users (
    user_id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    verification_status VARCHAR(20) DEFAULT 'unverified',
    account_type VARCHAR(20) DEFAULT 'standard'
);

-- Enhanced user profiles with more medical information
CREATE TABLE user_profiles (
    profile_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    first_name VARCHAR(50),
    last_name VARCHAR(50),
    date_of_birth DATE,
    gender VARCHAR(20),
    height FLOAT,
    weight FLOAT,
    blood_type VARCHAR(5),
    emergency_contact_name VARCHAR(100),
    emergency_contact_phone VARCHAR(20),
    has_insurance BOOLEAN DEFAULT FALSE,
    insurance_provider VARCHAR(100),
    insurance_id VARCHAR(50),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Improved allergies table with severity and reaction type
CREATE TABLE user_allergies (
    allergy_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    allergy_name VARCHAR(100) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    reaction_type VARCHAR(100),
    diagnosed_by_professional BOOLEAN DEFAULT FALSE,
    notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Enhanced medical conditions with more clinical details
CREATE TABLE user_conditions (
    condition_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    condition_name VARCHAR(100) NOT NULL,
    diagnosed_date DATE,
    diagnosed_by VARCHAR(100),
    treatment_status VARCHAR(20),
    severity VARCHAR(20),
    notes TEXT,
    is_chronic BOOLEAN DEFAULT FALSE,
    requires_monitoring BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Add medication history table
CREATE TABLE user_medications (
    medication_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    medication_name VARCHAR(100) NOT NULL,
    dosage VARCHAR(50),
    frequency VARCHAR(50),
    start_date DATE,
    end_date DATE,
    is_current BOOLEAN DEFAULT TRUE,
    prescribed_by VARCHAR(100),
    reason_for_taking TEXT,
    side_effects TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Improved diseases table
CREATE TABLE diseases (
    disease_id SERIAL PRIMARY KEY,
    disease_name VARCHAR(100) UNIQUE NOT NULL,
    common_name VARCHAR(100),
    medical_name VARCHAR(100),
    icd_10_code VARCHAR(20),
    causes TEXT,
    disease_category VARCHAR(50),
    contagious BOOLEAN DEFAULT FALSE,
    chronic BOOLEAN DEFAULT FALSE,
    requires_medical_attention VARCHAR(20) DEFAULT 'recommended',
    typical_recovery_time VARCHAR(50),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Add disease descriptions table for multilingual support
CREATE TABLE disease_descriptions (
    description_id SERIAL PRIMARY KEY,
    disease_id INTEGER NOT NULL REFERENCES diseases(disease_id) ON DELETE CASCADE,
    language_code VARCHAR(5) NOT NULL DEFAULT 'en',
    short_description TEXT NOT NULL,
    long_description TEXT,
    common_questions_answers JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (disease_id, language_code)
);

-- Improved symptoms table with separate entries
CREATE TABLE symptoms (
    symptom_id SERIAL PRIMARY KEY,
    symptom_name VARCHAR(100) UNIQUE NOT NULL,
    body_area VARCHAR(50),
    severity_indicator BOOLEAN DEFAULT FALSE,
    medical_term VARCHAR(100),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Junction table for disease-symptom relationship
CREATE TABLE disease_symptoms (
    id SERIAL PRIMARY KEY,
    disease_id INTEGER NOT NULL REFERENCES diseases(disease_id) ON DELETE CASCADE,
    symptom_id INTEGER NOT NULL REFERENCES symptoms(symptom_id) ON DELETE CASCADE,
    is_primary BOOLEAN DEFAULT FALSE,
    frequency VARCHAR(20), -- 'common', 'rare', 'sometimes'
    typical_severity VARCHAR(20), -- 'mild', 'moderate', 'severe'
    order_of_appearance INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (disease_id, symptom_id)
);

-- Treatments table for more flexibility
CREATE TABLE treatments (
    treatment_id SERIAL PRIMARY KEY,
    treatment_name VARCHAR(100) NOT NULL,
    treatment_type VARCHAR(50) NOT NULL, -- 'medication', 'procedure', 'lifestyle', etc.
    description TEXT,
    medical_specialties VARCHAR(100)[],
    typical_duration VARCHAR(50),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Junction table for disease-treatment relationship
CREATE TABLE disease_treatments (
    id SERIAL PRIMARY KEY,
    disease_id INTEGER NOT NULL REFERENCES diseases(disease_id) ON DELETE CASCADE,
    treatment_id INTEGER NOT NULL REFERENCES treatments(treatment_id) ON DELETE CASCADE,
    efficacy_rating INTEGER, -- 1-5 scale
    recommendation_level VARCHAR(20), -- 'first-line', 'alternative', 'last-resort'
    typical_duration VARCHAR(50),
    ordering INTEGER, -- for treatment sequence
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (disease_id, treatment_id)
);

-- Medications table instead of storing as strings
CREATE TABLE medications (
    medication_id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    generic_name VARCHAR(100),
    medication_class VARCHAR(100),
    form VARCHAR(50), -- 'tablet', 'capsule', 'liquid', etc.
    typical_dosage TEXT,
    requires_prescription BOOLEAN DEFAULT TRUE,
    common_side_effects TEXT[],
    interactions TEXT[],
    contraindications TEXT[],
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Junction table for disease-medication relationship
CREATE TABLE disease_medications (
    id SERIAL PRIMARY KEY,
    disease_id INTEGER NOT NULL REFERENCES diseases(disease_id) ON DELETE CASCADE,
    medication_id INTEGER NOT NULL REFERENCES medications(medication_id) ON DELETE CASCADE,
    typical_dosage TEXT,
    usage_notes TEXT,
    efficacy_rating INTEGER, -- 1-5 scale
    is_primary BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (disease_id, medication_id)
);

-- Enhanced precautions table
CREATE TABLE precautions (
    precaution_id SERIAL PRIMARY KEY,
    precaution_text TEXT NOT NULL,
    precaution_type VARCHAR(50), -- 'lifestyle', 'monitoring', 'prevention', etc.
    urgency_level VARCHAR(20), -- 'critical', 'important', 'advisory'
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Junction table for disease-precaution relationship
CREATE TABLE disease_precautions (
    id SERIAL PRIMARY KEY,
    disease_id INTEGER NOT NULL REFERENCES diseases(disease_id) ON DELETE CASCADE,
    precaution_id INTEGER NOT NULL REFERENCES precautions(precaution_id) ON DELETE CASCADE,
    ordering INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (disease_id, precaution_id, ordering)
);

-- Diet recommendations table
CREATE TABLE diet_recommendations (
    diet_id SERIAL PRIMARY KEY,
    recommendation_name VARCHAR(100) NOT NULL,
    description TEXT NOT NULL,
    food_groups_to_include TEXT[],
    food_groups_to_avoid TEXT[],
    meal_frequency VARCHAR(50),
    hydration_guidelines TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Junction table for disease-diet relationship
CREATE TABLE disease_diets (
    id SERIAL PRIMARY KEY,
    disease_id INTEGER NOT NULL REFERENCES diseases(disease_id) ON DELETE CASCADE,
    diet_id INTEGER NOT NULL REFERENCES diet_recommendations(diet_id) ON DELETE CASCADE,
    importance_level VARCHAR(20), -- 'critical', 'helpful', 'optional'
    adaptation_notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (disease_id, diet_id)
);

-- Exercise recommendations table
CREATE TABLE exercise_recommendations (
    exercise_id SERIAL PRIMARY KEY,
    exercise_name VARCHAR(100) NOT NULL,
    description TEXT NOT NULL,
    intensity_level VARCHAR(20), -- 'low', 'moderate', 'high'
    frequency VARCHAR(50),
    duration VARCHAR(50),
    contraindications TEXT[],
    preparation_instructions TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Junction table for disease-exercise relationship
CREATE TABLE disease_exercises (
    id SERIAL PRIMARY KEY,
    disease_id INTEGER NOT NULL REFERENCES diseases(disease_id) ON DELETE CASCADE,
    exercise_id INTEGER NOT NULL REFERENCES exercise_recommendations(exercise_id) ON DELETE CASCADE,
    adaptation_notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (disease_id, exercise_id)
);

-- Consultation tracking for better analysis
CREATE TABLE consultations (
    consultation_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    symptoms_text TEXT NOT NULL,
    consultation_method VARCHAR(50) DEFAULT 'web',
    device_info JSONB,
    ip_address VARCHAR(50),
    geo_location JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- More detailed consultation results
CREATE TABLE consultation_results (
    result_id SERIAL PRIMARY KEY,
    consultation_id INTEGER NOT NULL REFERENCES consultations(consultation_id) ON DELETE CASCADE,
    disease_id INTEGER NOT NULL REFERENCES diseases(disease_id) ON DELETE CASCADE,
    confidence_score FLOAT NOT NULL,
    is_primary BOOLEAN NOT NULL DEFAULT false,
    match_method VARCHAR(20) DEFAULT 'bert', -- 'bert', 'direct_match', 'symptom_match'
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Treatment plans for users
CREATE TABLE treatment_plans (
    plan_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    disease_id INTEGER NOT NULL REFERENCES diseases(disease_id) ON DELETE CASCADE,
    consultation_id INTEGER REFERENCES consultations(consultation_id),
    plan_name VARCHAR(100),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    start_date DATE NOT NULL,
    expected_duration VARCHAR(50),
    status VARCHAR(20) DEFAULT 'active',
    healthcare_provider VARCHAR(100),
    notes TEXT
);

-- Treatment steps with rich tracking
CREATE TABLE treatment_steps (
    step_id SERIAL PRIMARY KEY,
    plan_id INTEGER NOT NULL REFERENCES treatment_plans(plan_id) ON DELETE CASCADE,
    step_type VARCHAR(20) NOT NULL, -- 'medication', 'diet', 'exercise', 'precaution'
    reference_id INTEGER, -- ID in the respective table
    name VARCHAR(100) NOT NULL,
    description TEXT,
    frequency VARCHAR(100),
    duration VARCHAR(50),
    status VARCHAR(20) DEFAULT 'not_started',
    start_date DATE,
    completion_date DATE,
    ordering INTEGER,
    importance_level VARCHAR(20) DEFAULT 'normal', -- 'critical', 'high', 'normal', 'optional'
    reminder_frequency VARCHAR(50),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Step completion tracking
CREATE TABLE step_completions (
    completion_id SERIAL PRIMARY KEY,
    step_id INTEGER NOT NULL REFERENCES treatment_steps(step_id) ON DELETE CASCADE,
    completion_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    skipped BOOLEAN DEFAULT FALSE,
    skip_reason TEXT
);

-- Symptom logging for treatment plans
CREATE TABLE symptom_logs (
    log_id SERIAL PRIMARY KEY,
    plan_id INTEGER NOT NULL REFERENCES treatment_plans(plan_id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    symptom VARCHAR(100) NOT NULL,
    severity INTEGER CHECK (severity BETWEEN 1 AND 10),
    log_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    triggers TEXT[],
    time_of_day VARCHAR(20),
    duration VARCHAR(50)
);

-- Treatment plan notes
CREATE TABLE plan_notes (
    note_id SERIAL PRIMARY KEY,
    plan_id INTEGER NOT NULL REFERENCES treatment_plans(plan_id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    note_text TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    note_type VARCHAR(20) DEFAULT 'general' -- 'general', 'medication', 'symptom', 'appointment'
);

-- Medical appointment tracking
CREATE TABLE medical_appointments (
    appointment_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    plan_id INTEGER REFERENCES treatment_plans(plan_id) ON DELETE SET NULL,
    provider_name VARCHAR(100) NOT NULL,
    appointment_type VARCHAR(50),
    appointment_date TIMESTAMP NOT NULL,
    location VARCHAR(255),
    status VARCHAR(20) DEFAULT 'scheduled',
    notes TEXT,
    reminder_sent BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Medical test results tracking
CREATE TABLE medical_test_results (
    test_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    plan_id INTEGER REFERENCES treatment_plans(plan_id) ON DELETE SET NULL,
    test_name VARCHAR(100) NOT NULL,
    test_date DATE NOT NULL,
    results JSONB,
    interpretation TEXT,
    is_abnormal BOOLEAN,
    provider_name VARCHAR(100),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Feedback for system improvement
CREATE TABLE user_feedback (
    feedback_id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    consultation_id INTEGER REFERENCES consultations(consultation_id) ON DELETE SET NULL,
    feedback_type VARCHAR(20) NOT NULL, -- 'prediction', 'recommendation', 'interface', 'general'
    rating INTEGER CHECK (rating BETWEEN 1 AND 5),
    comments TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create comprehensive indexes for performance
CREATE INDEX idx_user_profiles_user_id ON user_profiles(user_id);
CREATE INDEX idx_user_allergies_user_id ON user_allergies(user_id);
CREATE INDEX idx_user_conditions_user_id ON user_conditions(user_id);
CREATE INDEX idx_user_medications_user_id ON user_medications(user_id);
CREATE INDEX idx_disease_symptoms_disease_id ON disease_symptoms(disease_id);
CREATE INDEX idx_disease_symptoms_symptom_id ON disease_symptoms(symptom_id);
CREATE INDEX idx_disease_treatments_disease_id ON disease_treatments(disease_id);
CREATE INDEX idx_disease_medications_disease_id ON disease_medications(disease_id);
CREATE INDEX idx_disease_precautions_disease_id ON disease_precautions(disease_id);
CREATE INDEX idx_disease_diets_disease_id ON disease_diets(disease_id);
CREATE INDEX idx_disease_exercises_disease_id ON disease_exercises(disease_id);
CREATE INDEX idx_consultation_results_consultation_id ON consultation_results(consultation_id);
CREATE INDEX idx_consultations_user_id ON consultations(user_id);
CREATE INDEX idx_treatment_plans_user_id ON treatment_plans(user_id);
CREATE INDEX idx_treatment_plans_disease_id ON treatment_plans(disease_id);
CREATE INDEX idx_treatment_steps_plan_id ON treatment_steps(plan_id);
CREATE INDEX idx_step_completions_step_id ON step_completions(step_id);
CREATE INDEX idx_symptom_logs_plan_id ON symptom_logs(plan_id);
CREATE INDEX idx_symptom_logs_user_id ON symptom_logs(user_id);
CREATE INDEX idx_plan_notes_plan_id ON plan_notes(plan_id);
CREATE INDEX idx_medical_appointments_user_id ON medical_appointments(user_id);
CREATE INDEX idx_medical_test_results_user_id ON medical_test_results(user_id);
CREATE INDEX idx_user_feedback_user_id ON user_feedback(user_id);

-- Add full-text search capabilities
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_symptoms_name_trgm ON symptoms USING gin(symptom_name gin_trgm_ops);
CREATE INDEX idx_diseases_name_trgm ON diseases USING gin(disease_name gin_trgm_ops);
CREATE INDEX idx_medications_name_trgm ON medications USING gin(name gin_trgm_ops);

-- Add to schema.sql

-- Lab test categories
CREATE TABLE lab_test_categories (
    category_id SERIAL PRIMARY KEY,
    category_name VARCHAR(100) NOT NULL,
    description TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Lab tests
CREATE TABLE lab_tests (
    test_id SERIAL PRIMARY KEY,
    test_name VARCHAR(100) NOT NULL,
    test_code VARCHAR(50),
    category_id INTEGER NOT NULL REFERENCES lab_test_categories(category_id),
    description TEXT,
    normal_range_min FLOAT,
    normal_range_max FLOAT,
    unit VARCHAR(20),
    sample_type VARCHAR(50),
    fasting_required BOOLEAN DEFAULT FALSE,
    preparation_instructions TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (test_code)
);

-- User lab results
CREATE TABLE user_lab_results (
    result_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    test_id INTEGER NOT NULL REFERENCES lab_tests(test_id),
    result_value FLOAT NOT NULL,
    test_date TIMESTAMP NOT NULL,
    reporting_date TIMESTAMP,
    ordering_physician VARCHAR(100),
    lab_name VARCHAR(100),
    status VARCHAR(50) DEFAULT 'completed',
    notes TEXT,
    attached_file_path VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Lab result flags
CREATE TABLE lab_result_flags (
    flag_id SERIAL PRIMARY KEY,
    result_id INTEGER NOT NULL REFERENCES user_lab_results(result_id),
    flag_type VARCHAR(50) NOT NULL, -- 'high', 'low', 'critical', 'abnormal'
    severity VARCHAR(20), -- 'mild', 'moderate', 'severe', 'critical'
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Lab test recommendations
CREATE TABLE lab_test_recommendations (
    recommendation_id SERIAL PRIMARY KEY,
    disease_id INTEGER NOT NULL REFERENCES diseases(disease_id),
    test_id INTEGER NOT NULL REFERENCES lab_tests(test_id),
    recommendation_reason TEXT,
    priority INTEGER DEFAULT 3, -- 1-5 scale
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (disease_id, test_id)
);

-- Lab test interpretation templates
CREATE TABLE lab_test_interpretations (
    interpretation_id SERIAL PRIMARY KEY,
    test_id INTEGER NOT NULL REFERENCES lab_tests(test_id),
    condition_name VARCHAR(100),
    interpretation_text TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes
CREATE INDEX idx_user_lab_results_user_id ON user_lab_results(user_id);
CREATE INDEX idx_user_lab_results_test_id ON user_lab_results(test_id);
CREATE INDEX idx_lab_test_recommendations_disease_id ON lab_test_recommendations(disease_id);
CREATE INDEX idx_lab_test_recommendations_test_id ON lab_test_recommendations(test_id);
CREATE INDEX idx_lab_result_flags_result_id ON lab_result_flags(result_id);
-- Medication schedules (for MedicationReminder)
CREATE TABLE IF NOT EXISTS medication_schedules (
    schedule_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    plan_id INTEGER REFERENCES treatment_plans(plan_id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scheduled_medications (
    med_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    schedule_id UUID NOT NULL REFERENCES medication_schedules(schedule_id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    frequency VARCHAR(100) NOT NULL DEFAULT 'Once daily',
    times_per_day INTEGER NOT NULL DEFAULT 1,
    schedule_times TEXT[] NOT NULL DEFAULT '{"08:00"}',
    start_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    end_date TIMESTAMP,
    reminders_enabled BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS medication_taken_logs (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    med_id UUID NOT NULL REFERENCES scheduled_medications(med_id) ON DELETE CASCADE,
    taken_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_medication_schedules_user_id ON medication_schedules(user_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_medications_schedule_id ON scheduled_medications(schedule_id);
CREATE INDEX IF NOT EXISTS idx_medication_taken_logs_med_id ON medication_taken_logs(med_id);

CREATE TABLE IF NOT EXISTS doctor_reviews (
    review_id  SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    hospital_id VARCHAR(100) NOT NULL,
    rating     SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    review_text TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, hospital_id)
);

CREATE INDEX IF NOT EXISTS idx_doctor_reviews_hospital ON doctor_reviews(hospital_id);
