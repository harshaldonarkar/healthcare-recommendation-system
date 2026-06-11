# import_doctors.py
import pandas as pd
import json
import os

# Define path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DATA_DIR = os.path.join(ROOT_DIR, 'data')

def import_doctors():
    """Import doctors data from CSV into a JSON file"""
    try:
        # Load the CSV file
        df = pd.read_csv(os.path.join(DATA_DIR, '/Users/harshaldonarkar/Desktop/college_project/healthcare-recommender/data/nhp_doctors.csv'))
        print(f"Loaded {len(df)} doctors from CSV")
        
        # Convert to dictionary format
        doctors_data = {}
        for index, row in df.iterrows():
            doctor_id = f"doc_{index}"
            doctors_data[doctor_id] = row.to_dict()
            
        # Save to JSON file
        with open(os.path.join(DATA_DIR, '/Users/harshaldonarkar/Desktop/college_project/healthcare-recommender/data/doctors_database.json'), 'w') as f:
            json.dump(doctors_data, f, indent=2)
            
        print(f"Saved doctors data to doctors_database.json")
        return True
    except Exception as e:
        print(f"Error importing doctors data: {e}")
        return False

if __name__ == "__main__":
    import_doctors()