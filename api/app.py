import logging, sys, hashlib
from flask import Blueprint, jsonify, Flask, request
from worker.workflows import process_locations
from utils.scrape import _normalize_url
from utils.slack import post_slack_log_message

# Configure logging to output to stdout
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    stream=sys.stdout
)

# Create the Flask app
app = Flask(__name__)

# Create blueprint and define its routes
main_blueprint = Blueprint("main", __name__,)

########## ROUTES ##########

@main_blueprint.route("/", methods=["GET"])
def healthcheck():
    '''
    Health check should always return 200.
    '''
    return 'ok', 200

@main_blueprint.route("/locations/<path:url>", methods=["GET"])
@main_blueprint.route("/locations", methods=["GET"])
def process_url(url=None):
    """
    Returns locations from provided URL
    
    Args:
        url: Full URL to the article (can be provided as path parameter or query parameter)
    """
    try:
        # Check if URL is provided as query parameter
        if url is None:
            url = request.args.get('url', '')
            if not url:
                return jsonify({"error": "No URL provided"}), 400
                
        # Normalize URL
        url = _normalize_url(url)
        
        # Log the request
        logging.info(f"LOCATION REQUEST: Processing URL: {url}")
        
        # Create a task to scrape the article asynchronously
        # Don't wait for the result - return immediately
        task = process_locations.apply_async(args=[url])
        
        # Log the task ID
        logging.info(f"LOCATION TASK CREATED: Task ID: {task.id} for URL: {url}")
        
        return jsonify({
            "status": "submitted",
            "message": "Article processing started",
            "task_id": task.id,
            "url": url,
            "output_filename": f"{hashlib.sha256(url.encode()).hexdigest()[:20]}.json"
        }), 202  # 202 Accepted
        
    except Exception as e:
        logging.error(f"LOCATION ERROR: Error processing URL: {str(e)}")
        import traceback
        logging.error(f"LOCATION ERROR TRACEBACK: {traceback.format_exc()}")
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


# Register blueprint
app.register_blueprint(main_blueprint)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5004)