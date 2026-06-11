# src/backend/utils.py

import logging
import json
import re

logger = logging.getLogger(__name__)

def parse_medicine_list(medicines_str):
    """Parse the medicines string into a list"""
    try:
        # Replace single quotes with double quotes for JSON parsing
        medicines_str = medicines_str.replace("'", '"')
        # Handle any whitespace issues
        medicines_str = re.sub(r'\s+\[', '[', medicines_str)
        medicines_str = re.sub(r'\s+\]', ']', medicines_str)
        
        return json.loads(medicines_str)
    except Exception as e:
        logger.error(f"Error parsing medicines: {e}")
        logger.error(f"Problem string: {medicines_str}")
        # Fallback: basic string split and clean
        return [med.strip() for med in medicines_str.strip('[] "\'').split(',')]

def format_symptoms_for_display(symptoms_list):
    """Format a list of symptoms for display"""
    # Remove None and empty values
    symptoms = [s for s in symptoms_list if s]
    
    if not symptoms:
        return "No symptoms specified"
        
    if len(symptoms) == 1:
        return symptoms[0]
        
    if len(symptoms) == 2:
        return f"{symptoms[0]} and {symptoms[1]}"
        
    return ", ".join(symptoms[:-1]) + f", and {symptoms[-1]}"

def safe_get(dictionary, key, default=None):
    """Safely get a value from a dictionary"""
    try:
        return dictionary.get(key, default)
    except:
        return default

def calculate_severity(confidence_scores):
    """Calculate severity based on confidence scores"""
    if not confidence_scores:
        return "Unknown"
        
    highest_confidence = max(confidence_scores)
    
    if highest_confidence >= 90:
        return "High"
    elif highest_confidence >= 70:
        return "Medium"
    else:
        return "Low"