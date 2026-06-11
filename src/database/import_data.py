# src/database/import_data.py

import pandas as pd
import json
import psycopg2
from psycopg2.extras import execute_values
import re
import os
import sys
from dotenv import load_dotenv

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from backend.utils import parse_medicine_list

# Load environment variables
load_dotenv()

# Database connection parameters
DB_PARAMS = {
    'dbname': os.environ.get('DB_NAME', 'healthcare_system'),
    'user': os.environ.get('DB_USER', 'postgres'),
    'password': os.environ.get('DB_PASSWORD', 'password'),
    'host': os.environ.get('DB_HOST', 'localhost'),
    'port': os.environ.get('DB_PORT', '5432')
}

# Define paths
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DATA_DIR = os.path.join(ROOT_DIR, 'data')
CSV_FILE = os.path.join(DATA_DIR, 'medical_data_complete.csv')

def connect_to_db():
    """Create a connection to the database"""
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return None

def import_disease_data():
    """Import disease data from CSV into the database"""
    try:
        # Read CSV file
        df = pd.read_csv(CSV_FILE)
        print(f"Loaded {len(df)} diseases from CSV")
        
        # Connect to database
        conn = connect_to_db()
        if not conn:
            return False
        
        cursor = conn.cursor()
        
        # Begin transaction
        conn.autocommit = False
        
        # 1. Insert diseases
        print("Inserting diseases...")
        disease_data = []
        for _, row in df.iterrows():
            disease_data.append((row['Disease'], row['Causes']))
            
        insert_disease_query = """
            INSERT INTO diseases (disease_name, causes)
            VALUES %s
            RETURNING disease_id, disease_name;
        """
        
        disease_ids = {}
        execute_values(cursor, insert_disease_query, disease_data)
        for record in cursor.fetchall():
            disease_ids[record[1]] = record[0]  # Map disease_name to disease_id
        
        # 2. Insert symptoms
        print("Inserting symptoms...")
        symptom_data = []
        for _, row in df.iterrows():
            disease_id = disease_ids[row['Disease']]
            for i in range(1, 5):  # Symptom1 to Symptom4
                symptom_col = f'Symptom{i}'
                if symptom_col in row and pd.notna(row[symptom_col]):
                    symptom_data.append((disease_id, row[symptom_col], i))
        
        insert_symptom_query = """
            INSERT INTO disease_symptoms (disease_id, symptom_name, symptom_order)
            VALUES %s;
        """
        execute_values(cursor, insert_symptom_query, symptom_data)
        
        # 3. Insert medications
        print("Inserting medications...")
        medication_data = []
        for _, row in df.iterrows():
            disease_id = disease_ids[row['Disease']]
            if 'Medicines' in row and pd.notna(row['Medicines']):
                medicines = parse_medicine_list(row['Medicines'])
                for medicine in medicines:
                    # Clean up medicine name
                    medicine = medicine.strip('" ')
                    if medicine:  # Only add non-empty strings
                        medication_data.append((disease_id, medicine))
        
        insert_medication_query = """
            INSERT INTO disease_treatments (disease_id, medicine_name)
            VALUES %s;
        """
        execute_values(cursor, insert_medication_query, medication_data)
        
        # 4. Insert precautions
        print("Inserting precautions...")
        precaution_data = []
        for _, row in df.iterrows():
            disease_id = disease_ids[row['Disease']]
            for i in range(1, 5):  # Precaution1 to Precaution4
                precaution_col = f'Precaution{i}'
                if precaution_col in row and pd.notna(row[precaution_col]):# src/database/import_data.py (continued)
                    precaution_data.append((disease_id, row[precaution_col], i))
        
        insert_precaution_query = """
            INSERT INTO disease_precautions (disease_id, precaution_text, precaution_order)
            VALUES %s;
        """
        execute_values(cursor, insert_precaution_query, precaution_data)
        
        # 5. Insert diets
        print("Inserting diets...")
        diet_data = []
        for _, row in df.iterrows():
            disease_id = disease_ids[row['Disease']]
            if 'Diets' in row and pd.notna(row['Diets']):
                diet_data.append((disease_id, row['Diets']))
        
        insert_diet_query = """
            INSERT INTO disease_diets (disease_id, diet_recommendation)
            VALUES %s;
        """
        execute_values(cursor, insert_diet_query, diet_data)
        
        # 6. Insert workouts
        print("Inserting workouts...")
        workout_data = []
        for _, row in df.iterrows():
            disease_id = disease_ids[row['Disease']]
            if 'Workout' in row and pd.notna(row['Workout']):
                workout_data.append((disease_id, row['Workout']))
        
        insert_workout_query = """
            INSERT INTO disease_workouts (disease_id, workout_recommendation)
            VALUES %s;
        """
        execute_values(cursor, insert_workout_query, workout_data)
        
        # Commit all changes
        conn.commit()
        print("All data imported successfully!")
        
        # Close connection
        cursor.close()
        conn.close()
        
        return True
        
    except Exception as e:
        print(f"Error importing data: {e}")
        if 'conn' in locals() and conn:
            conn.rollback()
            conn.close()
        return False

if __name__ == "__main__":
    import_disease_data()