# src/backend/doctor_search.py

import json
import os
import math
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)

class DoctorSearch:
    """Handle doctor searching and recommendations with focus on city searching"""
    
    def __init__(self, data_file=None):
        """Initialize the doctor search module"""
        if not data_file:
            ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            DATA_DIR = os.path.join(ROOT_DIR, 'data')
            data_file = os.path.join(DATA_DIR, 'doctors_database.json')
            
        self.data_file = data_file
        self.doctors_data = {}
        
        try:
            with open(data_file, 'r') as f:
                self.doctors_data = json.load(f)
            logger.info(f"Loaded doctors data from {data_file}")
        except FileNotFoundError:
            logger.warning(f"No doctors data found at {data_file}")
        except json.JSONDecodeError:
            logger.error(f"Error reading {data_file}")
    
    def search_by_city(self, city: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Search for hospitals/doctors based on city
        
        Args:
            city: City name to search
            limit: Maximum number of results to return
            
        Returns:
            List of matching hospitals
        """
        if not city:
            return []
            
        city = city.lower()
        results = []
        
        for doctor_id, doctor in self.doctors_data.items():
            # Check if hospital is in the specified city
            location_match = False
            
            # Check different location fields
            location_fields = ['Town', 'District', 'Subdistrict', 'State', 'Location']
            for field in location_fields:
                if field in doctor and doctor[field] and city in str(doctor[field]).lower():
                    location_match = True
                    break
                    
            # Check address field
            if not location_match and 'Address_Original_First_Line' in doctor:
                if city in str(doctor['Address_Original_First_Line']).lower():
                    location_match = True
            
            if location_match:
                # Format the result
                formatted_hospital = self._format_hospital_data(doctor_id, doctor)
                results.append(formatted_hospital)
        
        # Sort results (we could enhance this with a relevance score later)
        results.sort(key=lambda x: x.get('rating', 0), reverse=True)
        
        return results[:limit]
    
    def get_all_cities(self) -> List[str]:
        """
        Get a list of all cities in the database
        
        Returns:
            List of unique city names
        """
        cities = set()
        
        for doctor in self.doctors_data.values():
            # Extract city from various fields
            if 'Town' in doctor and doctor['Town']:
                cities.add(str(doctor['Town']).strip())
            if 'District' in doctor and doctor['District']:
                cities.add(str(doctor['District']).strip())
            if 'Location' in doctor and doctor['Location']:
                location = str(doctor['Location']).strip()
                # Only add if it looks like a city name (not coordinates)
                if not ',' in location and not location.replace('.', '').isdigit():
                    cities.add(location)
        
        return sorted(list(cities))
    
    def recommend_hospitals_for_disease(self, disease: str, city: str = None, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Recommend hospitals based on a diagnosed disease and city
        
        Args:
            disease: The diagnosed disease
            city: City name (optional)
            limit: Maximum number of results
            
        Returns:
            List of recommended hospitals
        """
        # Map diseases to relevant specialties
        specialty_map = {
            'Malaria': ['General Medicine', 'Infectious Disease'],
            'Dengue': ['General Medicine', 'Infectious Disease'],
            'COVID-19': ['Pulmonology', 'General Medicine', 'Infectious Disease'],
            'Pneumonia': ['Pulmonology', 'General Medicine'],
            'Diabetes': ['Endocrinology', 'General Medicine'],
            'Hypertension': ['Cardiology', 'General Medicine'],
            'Arthritis': ['Rheumatology', 'Orthopedics'],
            'Asthma': ['Pulmonology', 'Allergy and Immunology'],
            'Migraine': ['Neurology', 'General Medicine'],
            'Depression': ['Psychiatry', 'Psychology'],
            'Anxiety': ['Psychiatry', 'Psychology'],
            # Add more disease-specialty mappings
        }
        
        # Get relevant specialties for the disease
        relevant_specialties = specialty_map.get(disease, ['General Medicine'])
        
        # Start with city search if provided
        if city:
            results = self.search_by_city(city, limit=limit*2)  # Get extra results to filter
        else:
            # If no city, get all hospitals
            results = [self._format_hospital_data(doc_id, doc) for doc_id, doc in self.doctors_data.items()][:limit*3]
        
        # Now filter and score based on specialties
        for hospital in results:
            specialty_score = 0
            hospital_specialties = hospital.get('specialty', '').lower()
            
            # Check if hospital has relevant specialties
            for specialty in relevant_specialties:
                if specialty.lower() in hospital_specialties:
                    specialty_score += 1
            
            # Adjust rating based on specialty match
            hospital['specialty_score'] = specialty_score
            hospital['rating'] = hospital.get('rating', 0) + specialty_score
        
        # Re-sort based on updated ratings
        results.sort(key=lambda x: (x.get('specialty_score', 0), x.get('rating', 0)), reverse=True)
        
        return results[:limit]
    
    def _format_hospital_data(self, hospital_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Format hospital data for API response"""
        # Calculate a simple rating based on available data
        rating = 0
        if data.get('Accreditation'):
            rating += 1
        if data.get('Emergency_Services'):
            rating += 1
        if data.get('Total_Num_Beds'):
            try:
                beds = int(data.get('Total_Num_Beds', 0))
                rating += min(beds, 300) / 100  # Up to 3 points for beds
            except:
                pass
        
        # Format address
        address_parts = []
        for field in ['Address_Original_First_Line', 'Town', 'District', 'State', 'Pincode']:
            if data.get(field):
                address_parts.append(str(data.get(field)))
        address = ', '.join(address_parts)
        
        # Format contact info
        contact_info = {}
        for field in ['Telephone', 'Mobile_Number', 'Emergency_Num', 'Hospital_Primary_Email_Id', 'Website']:
            if data.get(field):
                key = field.replace('_', ' ').title()
                contact_info[key] = data.get(field)
        
        # Extract coordinates if available
        coordinates = None
        if data.get('Location_Coordinates'):
            try:
                coords = data.get('Location_Coordinates').split(',')
                if len(coords) == 2:
                    coordinates = {
                        'latitude': float(coords[0]),
                        'longitude': float(coords[1])
                    }
            except:
                pass
        
        return {
            'hospital_id': hospital_id,
            'name': data.get('Hospital_Name', 'Unknown Hospital'),
            'specialty': data.get('Specialties', ''),
            'address': address,
            'contact_info': contact_info,
            'coordinates': coordinates,
            'rating': rating,
            'facilities': data.get('Facilities', '').split(',') if data.get('Facilities') else [],
            'type': data.get('Hospital_Category', 'Unknown'),
            'care_type': data.get('Hospital_Care_Type', 'Unknown'),
            'bed_count': data.get('Total_Num_Beds', 'Unknown'),
            'established': data.get('Establised_Year', 'Unknown'),
            'emergency_services': bool(data.get('Emergency_Services')),
            'location': {
                'city': data.get('Town', ''),
                'district': data.get('District', ''),
                'state': data.get('State', '')
            }
        }
