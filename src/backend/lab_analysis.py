# src/backend/lab_analysis.py

import pandas as pd
import numpy as np
import json
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
import re

logger = logging.getLogger(__name__)

class PathlabAnalyzer:
    """Analyze medical pathology lab results and provide recommendations"""
    
    def __init__(self, medical_data_path: str):
        self.medical_data = pd.read_csv(medical_data_path)
        
        # Common lab tests with normal ranges.
        # Ranges use half-open convention: low <= value < high (enforced in _interpret_result).
        # Gender-specific tests (hemoglobin, creatinine, HDL) store a single
        # conservative range here; analyze_lab_results accepts gender to override.
        self.lab_tests = {
            # ── Blood sugar ────────────────────────────────────────────────
            'blood_glucose_fasting': {
                'normal_range': (70, 100),
                'unit': 'mg/dL',
                'interpretation': {
                    (0,    70):  'Hypoglycemia',
                    (70,  100):  'Normal',
                    (100, 126):  'Prediabetes (Impaired Fasting Glucose)',
                    (126, 200):  'Diabetes',
                    (200, 999):  'Severe hyperglycemia',
                }
            },
            'hba1c': {
                'normal_range': (4.0, 5.7),
                'unit': '%',
                'interpretation': {
                    (0.0, 5.7): 'Normal',
                    (5.7, 6.5): 'Prediabetes',
                    (6.5, 8.0): 'Diabetes (controlled)',
                    (8.0, 15.0): 'Diabetes (poorly controlled)',
                }
            },
            # ── Lipids ────────────────────────────────────────────────────
            'total_cholesterol': {
                'normal_range': (125, 200),
                'unit': 'mg/dL',
                'interpretation': {
                    (0,   200): 'Desirable',
                    (200, 240): 'Borderline high',
                    (240, 500): 'High',
                }
            },
            'ldl_cholesterol': {
                'normal_range': (0, 100),
                'unit': 'mg/dL',
                'interpretation': {
                    (0,   100): 'Optimal',
                    (100, 130): 'Near optimal',
                    (130, 160): 'Borderline high',
                    (160, 190): 'High',
                    (190, 500): 'Very high',
                }
            },
            'hdl_cholesterol': {
                'normal_range': (40, 200),   # men ≥40, women ≥50 — see gender override
                'unit': 'mg/dL',
                'interpretation': {
                    (0,   40):  'Low — increased cardiovascular risk',
                    (40,  60):  'Acceptable',
                    (60,  200): 'Optimal (protective)',
                }
            },
            'triglycerides': {
                'normal_range': (0, 150),
                'unit': 'mg/dL',
                'interpretation': {
                    (0,   150): 'Normal',
                    (150, 200): 'Borderline high',
                    (200, 500): 'High',
                    (500, 2000): 'Very high — pancreatitis risk',
                }
            },
            # ── CBC ───────────────────────────────────────────────────────
            'hemoglobin': {
                'normal_range': (12.0, 17.5),   # broad; gender override applied at runtime
                'unit': 'g/dL',
                'normal_range_male':   (13.5, 17.5),
                'normal_range_female': (12.0, 15.5),
                'interpretation': {
                    (0,    8.0):  'Severe anemia',
                    (8.0,  10.0): 'Moderate anemia',
                    (10.0, 12.0): 'Mild anemia',
                    (12.0, 17.5): 'Normal',
                    (17.5, 25.0): 'Polycythemia',
                }
            },
            'rbc_count': {
                'normal_range': (4.2, 5.9),
                'unit': '×10⁶/μL',
                'interpretation': {
                    (0,   4.2): 'Low',
                    (4.2, 5.9): 'Normal',
                    (5.9, 9.0): 'High',
                }
            },
            'hematocrit': {
                'normal_range': (36, 50),
                'unit': '%',
                'interpretation': {
                    (0,  36): 'Low (anemia)',
                    (36, 50): 'Normal',
                    (50, 65): 'High (polycythemia)',
                }
            },
            'mcv': {
                'normal_range': (80, 100),
                'unit': 'fL',
                'interpretation': {
                    (0,  80):  'Microcytic (iron deficiency / thalassemia)',
                    (80, 100): 'Normal (normocytic)',
                    (100, 150): 'Macrocytic (B12/folate deficiency)',
                }
            },
            'mch': {
                'normal_range': (27, 33),
                'unit': 'pg',
                'interpretation': {
                    (0,  27): 'Hypochromic',
                    (27, 33): 'Normal',
                    (33, 60): 'Hyperchromic',
                }
            },
            'mchc': {
                'normal_range': (32, 36),
                'unit': 'g/dL',
                'interpretation': {
                    (0,  32): 'Hypochromic',
                    (32, 36): 'Normal',
                    (36, 50): 'Hyperchromic',
                }
            },
            'platelet_count': {
                'normal_range': (150, 450),
                'unit': '×10³/μL',
                'interpretation': {
                    (0,   100): 'Severe thrombocytopenia',
                    (100, 150): 'Mild thrombocytopenia',
                    (150, 450): 'Normal',
                    (450, 600): 'Mild thrombocytosis',
                    (600, 2000): 'Thrombocytosis',
                }
            },
            'wbc_count': {
                'normal_range': (4.5, 11.0),
                'unit': '×10³/μL',
                'interpretation': {
                    (0,    4.5): 'Leukopenia',
                    (4.5,  11.0): 'Normal',
                    (11.0, 15.0): 'Mild leukocytosis',
                    (15.0, 20.0): 'Moderate leukocytosis',
                    (20.0, 100.0): 'Severe leukocytosis',
                }
            },
            # ── Kidney ────────────────────────────────────────────────────
            'creatinine': {
                'normal_range': (0.6, 1.3),   # men 0.7–1.3, women 0.6–1.1
                'unit': 'mg/dL',
                'normal_range_male':   (0.7, 1.3),
                'normal_range_female': (0.6, 1.1),
                'interpretation': {
                    (0,   0.6): 'Low (muscle wasting / malnutrition)',
                    (0.6, 1.3): 'Normal',
                    (1.3, 2.0): 'Mild kidney impairment',
                    (2.0, 5.0): 'Moderate kidney impairment',
                    (5.0, 15.0): 'Severe kidney impairment / failure',
                }
            },
            'urea': {
                'normal_range': (7, 20),
                'unit': 'mmol/L',
                'interpretation': {
                    (0,  7):  'Low',
                    (7,  20): 'Normal',
                    (20, 50): 'Elevated (kidney impairment / dehydration)',
                    (50, 200): 'Severely elevated',
                }
            },
            'bun_nitrogen': {
                'normal_range': (7, 25),
                'unit': 'mg/dL',
                'interpretation': {
                    (0,  7):  'Low',
                    (7,  25): 'Normal',
                    (25, 50): 'Elevated',
                    (50, 200): 'Severely elevated',
                }
            },
            'uric_acid': {
                'normal_range': (3.5, 7.2),
                'unit': 'mg/dL',
                'interpretation': {
                    (0,   3.5): 'Low',
                    (3.5, 7.2): 'Normal',
                    (7.2, 10.0): 'Hyperuricemia (gout risk)',
                    (10.0, 20.0): 'Severe hyperuricemia',
                }
            },
            # ── Electrolytes ──────────────────────────────────────────────
            'sodium': {
                'normal_range': (136, 145),
                'unit': 'mEq/L',
                'interpretation': {
                    (0,   136): 'Hyponatremia',
                    (136, 145): 'Normal',
                    (145, 200): 'Hypernatremia',
                }
            },
            'potassium': {
                'normal_range': (3.5, 5.0),
                'unit': 'mEq/L',
                'interpretation': {
                    (0,   3.5): 'Hypokalemia',
                    (3.5, 5.0): 'Normal',
                    (5.0, 15.0): 'Hyperkalemia',
                }
            },
            'chloride': {
                'normal_range': (98, 107),
                'unit': 'mEq/L',
                'interpretation': {
                    (0,   98):  'Hypochloremia',
                    (98,  107): 'Normal',
                    (107, 200): 'Hyperchloremia',
                }
            },
            # ── Liver ─────────────────────────────────────────────────────
            'alt_sgpt': {
                'normal_range': (7, 40),
                'unit': 'IU/L',
                'interpretation': {
                    (0,   40):  'Normal',
                    (40,  80):  'Mildly elevated',
                    (80,  200): 'Moderately elevated',
                    (200, 5000): 'Markedly elevated',
                }
            },
            'ast_sgot': {
                'normal_range': (8, 40),
                'unit': 'IU/L',
                'interpretation': {
                    (0,   40):  'Normal',
                    (40,  80):  'Mildly elevated',
                    (80,  200): 'Moderately elevated',
                    (200, 5000): 'Markedly elevated',
                }
            },
            'bilirubin': {
                'normal_range': (0.2, 1.2),
                'unit': 'mg/dL',
                'interpretation': {
                    (0,   1.2): 'Normal',
                    (1.2, 3.0): 'Mild hyperbilirubinemia',
                    (3.0, 10.0): 'Moderate (jaundice likely)',
                    (10.0, 50.0): 'Severe hyperbilirubinemia',
                }
            },
            'alkaline_phosphatase': {
                'normal_range': (44, 147),
                'unit': 'IU/L',
                'interpretation': {
                    (0,   44):  'Low',
                    (44,  147): 'Normal',
                    (147, 400): 'Elevated (liver / bone disease)',
                    (400, 2000): 'Markedly elevated',
                }
            },
            'ggt': {
                'normal_range': (9, 48),
                'unit': 'IU/L',
                'interpretation': {
                    (0,  48):  'Normal',
                    (48, 120): 'Mildly elevated',
                    (120, 2000): 'Elevated (alcohol / liver disease)',
                }
            },
            # ── Thyroid ───────────────────────────────────────────────────
            'thyroid_tsh': {
                'normal_range': (0.4, 4.5),
                'unit': 'mIU/L',
                'interpretation': {
                    (0,   0.4):  'Suppressed — possible hyperthyroidism',
                    (0.4, 4.5):  'Normal',
                    (4.5, 10.0): 'Mildly elevated — subclinical hypothyroidism',
                    (10.0, 20.0): 'Elevated — hypothyroidism',
                    (20.0, 100.0): 'Severely elevated — overt hypothyroidism',
                }
            },
            't3': {
                'normal_range': (80, 200),
                'unit': 'ng/dL',
                'interpretation': {
                    (0,   80):  'Low T3 (hypothyroid / sick euthyroid)',
                    (80,  200): 'Normal',
                    (200, 500): 'Elevated T3 (hyperthyroidism)',
                }
            },
            't4': {
                'normal_range': (5.1, 14.1),
                'unit': 'μg/dL',
                'interpretation': {
                    (0,   5.1):  'Low T4 (hypothyroidism)',
                    (5.1, 14.1): 'Normal',
                    (14.1, 30.0): 'Elevated T4 (hyperthyroidism)',
                }
            },
            # ── Vitamins / Iron ───────────────────────────────────────────
            'vitamin_d': {
                'normal_range': (30, 100),
                'unit': 'ng/mL',
                'interpretation': {
                    (0,   20):  'Deficiency',
                    (20,  30):  'Insufficiency',
                    (30,  100): 'Sufficient',
                    (100, 150): 'High — monitor for toxicity',
                }
            },
            'vitamin_b12': {
                'normal_range': (200, 900),
                'unit': 'pg/mL',
                'interpretation': {
                    (0,   200): 'Deficiency',
                    (200, 300): 'Low-normal',
                    (300, 900): 'Normal',
                    (900, 2000): 'High',
                }
            },
            'ferritin': {
                'normal_range': (12, 300),
                'unit': 'ng/mL',
                'interpretation': {
                    (0,   12):  'Low — iron deficiency',
                    (12,  300): 'Normal',
                    (300, 5000): 'Elevated (inflammation / iron overload)',
                }
            },
            'serum_iron': {
                'normal_range': (60, 170),
                'unit': 'μg/dL',
                'interpretation': {
                    (0,   60):  'Low — iron deficiency',
                    (60,  170): 'Normal',
                    (170, 500): 'Elevated',
                }
            },
        }
        
        # Disease-lab test correlations
        self.disease_lab_correlations = {
            'Diabetes': ['blood_glucose_fasting', 'hba1c'],
            'Coronary Artery Disease': ['total_cholesterol', 'ldl_cholesterol', 'hdl_cholesterol', 'triglycerides'],
            'Hypertension': ['creatinine', 'cholesterol'],
            'Anemia': ['hemoglobin', 'hematocrit', 'iron', 'ferritin'],
            'Hepatitis': ['alt_sgpt', 'ast_sgot', 'bilirubin'],
            'Thyroid Disorder': ['thyroid_tsh', 't3', 't4'],
            'Kidney Disease': ['creatinine', 'bun', 'uric_acid'],
            'Infection': ['wbc_count', 'esr', 'crp']
        }
    
    def analyze_lab_results(self, user_id: str, lab_results: List[Dict[str, Any]],
                            gender: Optional[str] = None) -> Dict[str, Any]:
        """
        Analyze lab results and provide comprehensive interpretation

        Args:
            user_id: User identifier
            lab_results: List of lab test results
            gender: 'male' or 'female' — used for sex-specific reference ranges

        Returns:
            Comprehensive analysis including interpretations and recommendations
        """
        gender = (gender or '').lower()
        try:
            interpretations = []
            abnormal_results = []
            potential_issues = []
            recommendations = []

            for result in lab_results:
                test_name = result.get('test_name', '').lower()
                value = result.get('value')

                # Get test info, applying sex-specific normal ranges where available
                test_info = self._get_test_info(test_name)
                if test_info and gender in ('male', 'female'):
                    sex_key = f'normal_range_{gender}'
                    if sex_key in test_info:
                        # Make a shallow copy so we don't mutate the class-level dict
                        test_info = dict(test_info)
                        test_info['normal_range'] = test_info[sex_key]

                if test_info and value is not None:
                    interpretation = self._interpret_result(test_info, value)
                    interpretations.append({
                        'test_name': test_name,
                        'value': value,
                        'unit': test_info.get('unit'),
                        'normal_range': test_info.get('normal_range'),
                        'interpretation': interpretation['interpretation'],
                        'severity': interpretation.get('severity'),
                        'flag': interpretation.get('flag')
                    })
                    
                    if interpretation.get('flag'):
                        abnormal_results.append({
                            'test_name': test_name,
                            'value': value,
                            'interpretation': interpretation['interpretation'],
                            'severity': interpretation.get('severity')
                        })
            
            # Identify potential health issues
            potential_issues = self._identify_health_issues(interpretations)
            
            # Generate recommendations
            recommendations = self._generate_recommendations(interpretations, potential_issues)
            
            # Create summary
            summary = self._create_summary(interpretations, abnormal_results, potential_issues)
            
            return {
                'interpretations': interpretations,
                'abnormal_results': abnormal_results,
                'potential_issues': potential_issues,
                'recommendations': recommendations,
                'summary': summary,
                'requires_medical_attention': self._check_medical_attention(interpretations)
            }
            
        except Exception as e:
            logger.error(f"Error analyzing lab results: {e}")
            return {'error': str(e)}
    
    def suggest_lab_tests(self, predicted_disease: str,
                          user_profile: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Suggest relevant lab tests based on predicted disease
        
        Args:
            predicted_disease: Predicted disease
            user_profile: User profile containing medical history
            
        Returns:
            List of recommended lab tests
        """
        try:
            recommended_tests = []
            
            # Get tests relevant to the disease
            disease_tests = self.disease_lab_correlations.get(predicted_disease, [])
            
            for test_name in disease_tests:
                test_info = self.lab_tests.get(test_name, {})
                
                recommended_tests.append({
                    'test_name': test_name,
                    'reason': f'Relevant for {predicted_disease} diagnosis/monitoring',
                    'priority': self._get_test_priority(test_name, predicted_disease),
                    'preparation_needed': self._get_preparation_instructions(test_name),
                    'cost_estimate': self._get_cost_estimate(test_name)
                })
            
            # Add additional tests based on user profile
            if user_profile:
                additional_tests = self._get_profile_based_tests(user_profile)
                for test in additional_tests:
                    if test not in recommended_tests:
                        recommended_tests.append(test)
            
            # Sort by priority
            recommended_tests.sort(key=lambda x: x.get('priority', 3), reverse=True)
            
            return recommended_tests
            
        except Exception as e:
            logger.error(f"Error suggesting lab tests: {e}")
            return []
    
    def parse_lab_report(self, report_text: str) -> Dict[str, Any]:
        """
        Parse text from scanned lab reports using pattern matching
        
        Args:
            report_text: Text extracted from lab report
            
        Returns:
            Structured lab results
        """
        try:
            extracted_results = []
            
            # Define patterns for common lab report formats
            patterns = [
                r'([\w\s]+):\s*([0-9.]+)\s*([a-zA-Z/]+)',  # Test: Value Unit
                r'([A-Za-z][A-Za-z0-9\s]+)\s+([0-9.]+)\s*([a-zA-Z/]+)?',  # Test Value Unit
                r'([\w\s]+)\s*-\s*([0-9.]+)\s*([a-zA-Z/]+)?'  # Test - Value Unit
            ]
            
            for pattern in patterns:
                matches = re.finditer(pattern, report_text)
                for match in matches:
                    test_name = match.group(1).strip()
                    value = float(match.group(2))
                    unit = match.group(3).strip() if len(match.groups()) > 2 and match.group(3) else None
                    
                    # Normalize test name
                    normalized_name = self._normalize_test_name(test_name)
                    
                    if normalized_name:
                        extracted_results.append({
                            'test_name': normalized_name,
                            'value': value,
                            'unit': unit
                        })
            
            return {
                'extracted_results': extracted_results,
                'raw_text': report_text
            }
            
        except Exception as e:
            logger.error(f"Error parsing lab report: {e}")
            return {'error': str(e)}
    
    def _get_test_info(self, test_name: str) -> Optional[Dict[str, Any]]:
        """Get test information from database"""
        # Normalize test name for matching
        normalized_name = self._normalize_test_name(test_name)
        return self.lab_tests.get(normalized_name)
    
    def _normalize_test_name(self, test_name: str) -> str:
        """Normalize test name for consistent matching"""
        test_name = test_name.lower()
        
        # Common name variants
        name_map = {
            'glucose':              'blood_glucose_fasting',
            'fasting blood sugar':  'blood_glucose_fasting',
            'fbs':                  'blood_glucose_fasting',
            'hba1c':                'hba1c',
            'glycated hemoglobin':  'hba1c',
            'a1c':                  'hba1c',
            'cholesterol':          'total_cholesterol',
            'ldl':                  'ldl_cholesterol',
            'hdl':                  'hdl_cholesterol',
            'triglyceride':         'triglycerides',
            'tg':                   'triglycerides',
            'hemoglobin':           'hemoglobin',
            'hb':                   'hemoglobin',
            'hgb':                  'hemoglobin',
            'wbc':                  'wbc_count',
            'white blood cell':     'wbc_count',
            'leucocyte':            'wbc_count',
            'rbc':                  'rbc_count',
            'red blood cell':       'rbc_count',
            'hematocrit':           'hematocrit',
            'pcv':                  'hematocrit',
            'mcv':                  'mcv',
            'mch':                  'mch',
            'mchc':                 'mchc',
            'platelet':             'platelet_count',
            'plt':                  'platelet_count',
            'creatinine':           'creatinine',
            'urea':                 'urea',
            'bun':                  'bun_nitrogen',
            'blood urea nitrogen':  'bun_nitrogen',
            'uric acid':            'uric_acid',
            'sodium':               'sodium',
            'na':                   'sodium',
            'potassium':            'potassium',
            'k':                    'potassium',
            'chloride':             'chloride',
            'cl':                   'chloride',
            'alt':                  'alt_sgpt',
            'sgpt':                 'alt_sgpt',
            'ast':                  'ast_sgot',
            'sgot':                 'ast_sgot',
            'bilirubin':            'bilirubin',
            'total bilirubin':      'bilirubin',
            'alkaline phosphatase': 'alkaline_phosphatase',
            'alp':                  'alkaline_phosphatase',
            'ggt':                  'ggt',
            'gamma gt':             'ggt',
            'tsh':                  'thyroid_tsh',
            't3':                   't3',
            't4':                   't4',
            'vitamin d':            'vitamin_d',
            '25-oh vitamin d':      'vitamin_d',
            'vitamin b12':          'vitamin_b12',
            'b12':                  'vitamin_b12',
            'ferritin':             'ferritin',
            'serum iron':           'serum_iron',
            'esr':                  'esr',
            'erythrocyte sedimentation': 'esr',
            'crp':                  'crp',
            'c reactive protein':   'crp',
            'inr':                  'inr',
            'prothrombin':          'inr',
        }
        
        for variant, standard in name_map.items():
            if variant in test_name:
                return standard
        
        return test_name
    
    def _interpret_result(self, test_info: Dict[str, Any], value: float) -> Dict[str, Any]:
        """Interpret a single lab result"""
        interpretation_map = test_info.get('interpretation', {})
        interpretation = 'Normal'
        severity = None
        flag = None
        
        # Find the appropriate interpretation range
        for range_tuple, range_interpretation in interpretation_map.items():
            if len(range_tuple) == 2 and range_tuple[0] <= value < range_tuple[1]:
                interpretation = range_interpretation
                
                # Determine severity based on deviation from normal
                normal_range = test_info.get('normal_range')
                if normal_range:
                    normal_min, normal_max = normal_range
                    if value < normal_min:
                        deviation = (normal_min - value) / normal_min
                        if deviation > 0.5:
                            severity = 'severe'
                            flag = 'low'
                        elif deviation > 0.2:
                            severity = 'moderate'
                            flag = 'low'
                        else:
                            severity = 'mild'
                            flag = 'low'
                    elif value > normal_max:
                        deviation = (value - normal_max) / normal_max
                        if deviation > 0.5:
                            severity = 'severe'
                            flag = 'high'
                        elif deviation > 0.2:
                            severity = 'moderate'
                            flag = 'high'
                        else:
                            severity = 'mild'
                            flag = 'high'
                break
        
        return {
            'interpretation': interpretation,
            'severity': severity,
            'flag': flag
        }
    
    def _identify_health_issues(self, interpretations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Identify potential health issues based on lab results"""
        issues = []
        
        # Pattern matching for common health issues
        test_values = {interp['test_name']: interp['value'] for interp in interpretations}
        
        # Diabetes screening
        if 'blood_glucose_fasting' in test_values and test_values['blood_glucose_fasting'] > 125:
            issues.append({
                'condition': 'Diabetes',
                'confidence': 'high' if test_values['blood_glucose_fasting'] > 150 else 'moderate',
                'supporting_tests': ['blood_glucose_fasting']
            })
        
        # Cholesterol issues
        cholesterol_tests = {
            'total_cholesterol': lambda v: v >= 200,
            'ldl_cholesterol':   lambda v: v >= 130,
            'hdl_cholesterol':   lambda v: v < 40,
            'triglycerides':     lambda v: v >= 150,
        }
        abnormal_cholesterol = [
            test for test, is_abnormal in cholesterol_tests.items()
            if test in test_values and is_abnormal(test_values[test])
        ]
        if abnormal_cholesterol:
            issues.append({
                'condition': 'Dyslipidemia',
                'confidence': 'moderate' if len(abnormal_cholesterol) > 1 else 'low',
                'supporting_tests': abnormal_cholesterol
            })
        
        # Liver function
        liver_tests = ['alt_sgpt', 'ast_sgot']
        elevated_liver = [test for test in liver_tests if test in test_values and test_values[test] > 40]
        if elevated_liver:
            issues.append({
                'condition': 'Liver dysfunction',
                'confidence': 'moderate' if len(elevated_liver) > 1 else 'low',
                'supporting_tests': elevated_liver
            })
        
        # Kidney function
        if 'creatinine' in test_values and test_values['creatinine'] > 1.2:
            issues.append({
                'condition': 'Kidney impairment',
                'confidence': 'moderate',
                'supporting_tests': ['creatinine']
            })
        
        # Anemia
        if 'hemoglobin' in test_values and test_values['hemoglobin'] < 12:
            issues.append({
                'condition': 'Anemia',
                'confidence': 'high' if test_values['hemoglobin'] < 10 else 'moderate',
                'supporting_tests': ['hemoglobin']
            })

        # Thyroid dysfunction
        if 'thyroid_tsh' in test_values:
            tsh = test_values['thyroid_tsh']
            if tsh > 4.5:
                issues.append({
                    'condition': 'Hypothyroidism (suspected)',
                    'confidence': 'high' if tsh > 10 else 'moderate',
                    'supporting_tests': ['thyroid_tsh']
                })
            elif tsh < 0.4:
                issues.append({
                    'condition': 'Hyperthyroidism (suspected)',
                    'confidence': 'high' if tsh < 0.1 else 'moderate',
                    'supporting_tests': ['thyroid_tsh']
                })

        # Prediabetes (separate from diabetes)
        if 'blood_glucose_fasting' in test_values:
            fg = test_values['blood_glucose_fasting']
            if 100 <= fg <= 125:
                issues.append({
                    'condition': 'Prediabetes',
                    'confidence': 'moderate',
                    'supporting_tests': ['blood_glucose_fasting']
                })

        # HbA1c-based diabetes / prediabetes
        if 'hba1c' in test_values:
            a1c = test_values['hba1c']
            if a1c >= 6.5:
                issues.append({
                    'condition': 'Diabetes',
                    'confidence': 'high',
                    'supporting_tests': ['hba1c']
                })
            elif 5.7 <= a1c < 6.5:
                issues.append({
                    'condition': 'Prediabetes',
                    'confidence': 'moderate',
                    'supporting_tests': ['hba1c']
                })

        return issues
    
    def _generate_recommendations(self, interpretations: List[Dict[str, Any]], 
                                  potential_issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Generate recommendations based on lab results"""
        recommendations = []
        
        for issue in potential_issues:
            condition = issue['condition']
            
            if condition == 'Diabetes':
                recommendations.extend([
                    {
                        'category': 'medical',
                        'recommendation': 'Consult an endocrinologist for diabetes management',
                        'priority': 'high'
                    },
                    {
                        'category': 'lifestyle',
                        'recommendation': 'Adopt a low glycemic index diet',
                        'priority': 'high'
                    },
                    {
                        'category': 'monitoring',
                        'recommendation': 'Regular blood glucose monitoring',
                        'priority': 'high'
                    }
                ])
            
            elif condition == 'Dyslipidemia':
                recommendations.extend([
                    {
                        'category': 'medical',
                        'recommendation': 'Consult a cardiologist for lipid management',
                        'priority': 'moderate'
                    },
                    {
                        'category': 'lifestyle',
                        'recommendation': 'Adopt a heart-healthy diet low in saturated fats',
                        'priority': 'high'
                    },
                    {
                        'category': 'exercise',
                        'recommendation': 'Regular aerobic exercise (30 minutes daily)',
                        'priority': 'high'
                    }
                ])
            
            elif condition == 'Liver dysfunction':
                recommendations.extend([
                    {
                        'category': 'medical',
                        'recommendation': 'Consult a hepatologist for liver function evaluation',
                        'priority': 'high'
                    },
                    {
                        'category': 'lifestyle',
                        'recommendation': 'Avoid alcohol and hepatotoxic medications',
                        'priority': 'high'
                    }
                ])
            
            elif condition == 'Kidney impairment':
                recommendations.extend([
                    {
                        'category': 'medical',
                        'recommendation': 'Consult a nephrologist for kidney function assessment',
                        'priority': 'high'
                    },
                    {
                        'category': 'lifestyle',
                        'recommendation': 'Ensure adequate hydration and limit protein intake',
                        'priority': 'moderate'
                    }
                ])
            
            elif condition == 'Anemia':
                recommendations.extend([
                    {
                        'category': 'medical',
                        'recommendation': 'Consult a hematologist for anemia evaluation',
                        'priority': 'moderate'
                    },
                    {
                        'category': 'nutrition',
                        'recommendation': 'Iron-rich diet or supplements as prescribed',
                        'priority': 'high'
                    }
                ])

            elif condition in ('Hypothyroidism (suspected)', 'Hyperthyroidism (suspected)'):
                recommendations.extend([
                    {
                        'category': 'medical',
                        'recommendation': 'Consult an endocrinologist for thyroid evaluation; T3/T4 tests may be needed',
                        'priority': 'high'
                    },
                    {
                        'category': 'monitoring',
                        'recommendation': 'Repeat TSH in 6–8 weeks to confirm trend',
                        'priority': 'moderate'
                    }
                ])

            elif condition == 'Prediabetes':
                recommendations.extend([
                    {
                        'category': 'lifestyle',
                        'recommendation': 'Adopt a low-carbohydrate diet and increase physical activity',
                        'priority': 'high'
                    },
                    {
                        'category': 'monitoring',
                        'recommendation': 'Recheck fasting glucose and HbA1c in 3–6 months',
                        'priority': 'moderate'
                    }
                ])

        return recommendations
    
    def _create_summary(self, interpretations: List[Dict[str, Any]], 
                        abnormal_results: List[Dict[str, Any]], 
                        potential_issues: List[Dict[str, Any]]) -> str:
        """Create a summary of lab results"""
        if not abnormal_results:
            return "Your lab results are within normal ranges."
        
        summary = f"Analysis of {len(interpretations)} lab tests revealed {len(abnormal_results)} abnormal result(s).\n\n"
        
        if potential_issues:
            summary += "Potential health concerns identified:\n"
            for issue in potential_issues:
                summary += f"- {issue['condition']} (confidence: {issue['confidence']})\n"
        
        summary += "\nRecommendation: Review results with your healthcare provider for proper interpretation and follow-up care."
        
        return summary
    
    def _check_medical_attention(self, interpretations: List[Dict[str, Any]]) -> bool:
        """Check if lab results require immediate medical attention.

        Uses (low, high) pairs — value < low or value >= high triggers urgent flag.
        None means "no lower / no upper bound applies".
        """
        # (critical_low, critical_high) — None means that boundary is not applicable
        critical_thresholds = {
            'blood_glucose_fasting': (40,   400),
            'creatinine':            (None, 5.0),
            'platelet_count':        (20,   None),
            'hemoglobin':            (7.0,  None),
            'wbc_count':             (2.0,  30.0),
            'sodium':                (120,  160),
            'potassium':             (2.5,  6.5),
            'alt_sgpt':              (None, 500),
            'ast_sgot':              (None, 500),
            'bilirubin':             (None, 15.0),
            'thyroid_tsh':           (0.05, 20.0),
            'inr':                   (None, 4.0),
        }

        for interp in interpretations:
            test_name = interp['test_name']
            value = interp['value']
            if test_name not in critical_thresholds:
                continue
            lo, hi = critical_thresholds[test_name]
            if lo is not None and value < lo:
                return True
            if hi is not None and value >= hi:
                return True

        return False
    
    def _get_test_priority(self, test_name: str, disease: str) -> int:
        """Get priority for a test (1-5 scale)"""
        # Default priority mappings
        priority_map = {
            ('blood_glucose_fasting', 'Diabetes'): 5,
            ('hba1c', 'Diabetes'): 5,
            ('total_cholesterol', 'Coronary Artery Disease'): 4,
            ('creatinine', 'Hypertension'): 4,
            ('thyroid_tsh', 'Thyroid Disorder'): 5
        }
        
        return priority_map.get((test_name, disease), 3)
    
    def _get_preparation_instructions(self, test_name: str) -> str:
        """Get preparation instructions for lab tests"""
        preparation_map = {
            'blood_glucose_fasting': 'Fast for 8-12 hours before test',
            'lipid_profile': 'Fast for 9-12 hours before test',
            'hba1c': 'No special preparation required',
            'thyroid_tsh': 'No special preparation required, but inform doctor of medications'
        }
        
        return preparation_map.get(test_name, 'No special preparation required')
    
    def _get_cost_estimate(self, test_name: str) -> str:
        """Get cost estimate for lab tests (prices in INR, approximate)"""
        cost_map = {
            'blood_glucose_fasting': '₹80–150',
            'hba1c':                 '₹400–700',
            'total_cholesterol':     '₹100–200',
            'ldl_cholesterol':       '₹150–300',
            'hdl_cholesterol':       '₹150–300',
            'triglycerides':         '₹100–200',
            'complete_blood_count':  '₹200–400',
            'hemoglobin':            '₹80–150',
            'wbc_count':             '₹80–150',
            'platelet_count':        '₹80–150',
            'creatinine':            '₹100–200',
            'urea':                  '₹80–150',
            'bun_nitrogen':          '₹80–150',
            'uric_acid':             '₹100–200',
            'alt_sgpt':              '₹100–200',
            'ast_sgot':              '₹100–200',
            'bilirubin':             '₹100–200',
            'alkaline_phosphatase':  '₹100–200',
            'ggt':                   '₹150–300',
            'thyroid_tsh':           '₹300–600',
            't3':                    '₹200–400',
            't4':                    '₹200–400',
            'vitamin_d':             '₹800–1500',
            'vitamin_b12':           '₹500–900',
            'ferritin':              '₹400–700',
            'serum_iron':            '₹200–350',
            'sodium':                '₹80–150',
            'potassium':             '₹80–150',
            'chloride':              '₹80–150',
            'esr':                   '₹60–120',
            'crp':                   '₹250–500',
            'inr':                   '₹150–300',
        }
        return cost_map.get(test_name, 'Contact lab for pricing')
    
    def _get_profile_based_tests(self, user_profile: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get additional recommended tests based on user profile"""
        additional_tests = []
        
        conditions = user_profile.get('conditions', [])
        age = user_profile.get('age', 0)
        gender = user_profile.get('gender', '')
        
        # Age-based screening
        if age > 40:
            additional_tests.append({
                'test_name': 'lipid_profile',
                'reason': 'Cardiovascular screening for age 40+',
                'priority': 3,
                'preparation_needed': 'Fast for 9-12 hours before test',
                'cost_estimate': '$50-80'
            })
            
            if gender == 'male':
                additional_tests.append({
                    'test_name': 'prostate_specific_antigen',
                    'reason': 'Prostate cancer screening for men 40+',
                    'priority': 2,
                    'preparation_needed': 'No special preparation required',
                    'cost_estimate': '$40-60'
                })
            
            if gender == 'female':
                additional_tests.append({
                    'test_name': 'mammogram',
                    'reason': 'Breast cancer screening for women 40+',
                    'priority': 3,
                    'preparation_needed': 'Schedule test one week after menstrual period',
                    'cost_estimate': '$100-200'
                })
        
        # Condition-based tests
        for condition in conditions:
            if 'diabetes' in condition.lower():
                additional_tests.append({
                    'test_name': 'urine_microalbumin',
                    'reason': 'Kidney function monitoring for diabetes',
                    'priority': 4,
                    'preparation_needed': 'First morning urine sample preferred',
                    'cost_estimate': '$30-50'
                })
            
            if 'hypertension' in condition.lower():
                additional_tests.append({
                    'test_name': 'bun',
                    'reason': 'Kidney function monitoring for hypertension',
                    'priority': 3,
                    'preparation_needed': 'No special preparation required',
                    'cost_estimate': '$20-30'
                })
        
        return additional_tests