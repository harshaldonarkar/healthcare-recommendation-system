# src/backend/blueprints/doctors.py
import logging

from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash

from core import doctor_search, calculate_distance, login_required
import db

logger = logging.getLogger(__name__)

doctors_bp = Blueprint('doctors', __name__)

SPECIALTIES = sorted([
    "General Medicine", "Cardiology", "Dermatology", "Endocrinology",
    "Gastroenterology", "Hematology", "Infectious Disease", "Nephrology",
    "Neurology", "Oncology", "Orthopedics", "Pediatrics",
    "Psychiatry", "Pulmonology", "Rheumatology", "Urology",
    "Obstetrics and Gynecology", "Ophthalmology", "Otolaryngology",
    "Physical Medicine and Rehabilitation", "Allergy and Immunology",
])


@doctors_bp.route('/doctors/search')
def doctor_search_page():
    return render_template('doctor_search.html')


@doctors_bp.route('/api/doctors/cities', methods=['GET'])
def get_cities():
    """Get list of unique cities from doctor database for autocomplete."""
    try:
        cities = doctor_search.get_all_cities()
        response = jsonify({"cities": cities})
        response.headers['Content-Type'] = 'application/json'
        response.headers['Cache-Control'] = 'public, max-age=3600'
        return response
    except Exception as e:
        logger.exception(f"Error getting cities list: {e}")
        return jsonify({"error": "Failed to retrieve cities"}), 500


@doctors_bp.route('/doctors/recommend/', defaults={'disease': None})
@doctors_bp.route('/doctors/recommend/<disease>')
def doctor_recommendations_page(disease):
    if not disease:
        return redirect(url_for('doctors.doctor_search_page'))
    return render_template(
        'doctor_recommendations.html',
        user_id=session.get('user_id', 'anonymous'),
        plan_id=request.args.get('plan_id', ''),
        disease=disease,
    )


@doctors_bp.route('/hospitals/recommend/', defaults={'disease': None})
@doctors_bp.route('/hospitals/recommend/<disease>')
def hospital_recommendations_page(disease):
    if not disease:
        return redirect(url_for('doctors.doctor_search_page'))
    return render_template(
        'hospital_recommendations.html',
        disease=disease,
    )


@doctors_bp.route('/doctors/search', methods=['GET'])
def search_doctors():
    """Search hospitals by city (primary search method)."""
    try:
        city = request.args.get('city', request.args.get('location', ''))
        limit = request.args.get('limit', default=10, type=int)
        results = doctor_search.search_by_city(city, limit=limit)
        # Paginate if results exceed 20
        if len(results) > 20:
            results = results[:20]
        response = jsonify({"count": len(results), "results": results})
        response.headers['Content-Type'] = 'application/json'
        return response
    except Exception as e:
        logger.exception(f"Error searching doctors: {e}")
        return jsonify({"error": "Failed to search doctors"}), 500


@doctors_bp.route('/api/doctors/search', methods=['GET'])
def search_doctors_api():
    """Search hospitals by city (API variant)."""
    try:
        city = request.args.get('city', '')
        limit = request.args.get('limit', default=10, type=int)
        results = doctor_search.search_by_city(city, limit=limit)
        # Paginate if results exceed 20
        if len(results) > 20:
            results = results[:20]
        response = jsonify({"city": city, "count": len(results), "results": results})
        response.headers['Content-Type'] = 'application/json'
        return response
    except Exception as e:
        logger.exception(f"Error searching hospitals: {e}")
        return jsonify({"error": "Failed to search hospitals"}), 500


@doctors_bp.route('/api/doctors/recommend/<disease>', methods=['GET'])
def recommend_hospitals_api(disease):
    """Recommend hospitals for a specific disease."""
    try:
        city = request.args.get('city', '')
        limit = request.args.get('limit', default=5, type=int)
        recommendations = doctor_search.recommend_hospitals_for_disease(disease=disease, city=city, limit=limit)
        return jsonify({"disease": disease, "city": city,
                        "count": len(recommendations), "recommendations": recommendations})
    except Exception as e:
        logger.exception(f"Error recommending hospitals: {e}")
        return jsonify({"error": "Failed to get hospital recommendations"}), 500


@doctors_bp.route('/doctors/specialties', methods=['GET'])
def get_specialties():
    return jsonify({"specialties": SPECIALTIES})


@doctors_bp.route('/doctors/nearby', methods=['GET'])
def get_nearby_doctors():
    try:
        latitude = request.args.get('latitude', type=float)
        longitude = request.args.get('longitude', type=float)
        radius = request.args.get('radius', default=5, type=float)

        if not latitude or not longitude:
            return jsonify({"error": "Latitude and longitude are required"}), 400

        results = []
        for hospital_id, hospital in doctor_search.doctors_data.items():
            coords_str = hospital.get('Location_Coordinates')
            if coords_str:
                try:
                    lat_str, lng_str = coords_str.split(',')
                    distance = calculate_distance(latitude, longitude, float(lat_str), float(lng_str))
                    if distance <= radius:
                        hospital_data = doctor_search._format_hospital_data(hospital_id, hospital)
                        hospital_data['distance_km'] = round(distance, 2)
                        results.append(hospital_data)
                except Exception:
                    continue

        results.sort(key=lambda x: x.get('distance_km', 0))
        return jsonify({"latitude": latitude, "longitude": longitude,
                        "radius_km": radius, "count": len(results), "results": results})

    except Exception as e:
        logger.exception(f"Error finding nearby doctors: {e}")
        return jsonify({"error": "Failed to find nearby doctors"}), 500


# ---------------------------------------------------------------------------
# Doctor / Hospital Reviews
# ---------------------------------------------------------------------------

@doctors_bp.route('/doctors/<hospital_id>/reviews', methods=['GET'])
def hospital_reviews_page(hospital_id):
    """Show reviews for a single hospital."""
    hospital = doctor_search.doctors_data.get(hospital_id)
    if not hospital:
        return "Hospital not found", 404
    try:
        reviews = db.get_hospital_reviews(hospital_id)
        avg_info = db.get_hospital_avg_rating(hospital_id)
    except Exception:
        reviews = []
        avg_info = None
    return render_template(
        'hospital_reviews.html',
        hospital_id=hospital_id,
        hospital=doctor_search._format_hospital_data(hospital_id, hospital),
        reviews=reviews,
        avg_info=avg_info,
    )


@doctors_bp.route('/api/doctors/<hospital_id>/reviews', methods=['GET'])
def get_hospital_reviews_api(hospital_id):
    try:
        reviews = db.get_hospital_reviews(hospital_id)
        avg_info = db.get_hospital_avg_rating(hospital_id)
        return jsonify({'hospital_id': hospital_id, 'avg_info': avg_info, 'reviews': reviews})
    except Exception as e:
        logger.exception(f"Error fetching reviews: {e}")
        return jsonify({'error': 'Could not fetch reviews'}), 500


@doctors_bp.route('/api/doctors/<hospital_id>/reviews', methods=['POST'])
@login_required
def submit_hospital_review(hospital_id):
    data = request.get_json() or {}
    rating = data.get('rating')
    review_text = data.get('review_text', '').strip()
    if not rating or not isinstance(rating, int) or rating < 1 or rating > 5:
        return jsonify({'error': 'rating must be an integer between 1 and 5'}), 400
    try:
        review_id = db.add_doctor_review(session['user_id'], hospital_id, rating, review_text)
        return jsonify({'message': 'Review submitted', 'review_id': review_id})
    except Exception as e:
        logger.exception(f"Error submitting review: {e}")
        return jsonify({'error': 'Could not save review — database may be unavailable'}), 500
