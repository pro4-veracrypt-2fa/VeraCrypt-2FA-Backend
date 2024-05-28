import random
import string
import time
 
from flask import Flask, jsonify, request
 
app = Flask(__name__, template_folder='templates')
 
 
pairing_codes = {}
device_database = {}
awaiting_2fa = {}
 
 
# Called by the PC
@app.route("/setup/new", methods=["POST"])
def generate_pairing_code():
    """
        Function creates a random code with length 8 for the given id.
 
        @returns ```json
        {
            "pairing_code": "random_code"
        }
        ```
 
        @returns 400 Bad Request: ```json
        {
            "error": "Missing 'pc-id' or 'pc-name' in request"
        }
        ```
    """
    json = request.get_json()
    if json.get("pc-id") is None or json.get("pc-name") is None:
        # Return Bad Request (400) if the request does not contain the required fields
        return jsonify({"error": "Missing 'pc-id' or 'pc-name' in request"}), 400
 
    requesting_pc_id = request.get_json()["pc-id"]
    requesting_pc_name = request.get_json()["pc-name"]
 
    # Generate a random pairing code
    pairing_code = ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8))
    pairing_codes[pairing_code] = {
        "pc_id": requesting_pc_id,
        "pc_name": requesting_pc_name
    }
 
    return jsonify({"pairing_code": pairing_code})
 
 
# Called by the smartphone
@app.route("/setup/pair", methods=["POST"])
def accept_pairing():
    """
        Function to compare the pairing code and associate two devices.
 
        @returns 200 OK: ```json
        {
            "accepted": true,
            "pc_name": <name of pc>
        }
        ```
 
        @returns 400 Bad Request: ```json
        {
            "error": "Missing 'smartphone-id' or 'pairing_code' in request"
        }
        ```
    """
    json = request.get_json()
    if json.get("smartphone-id") is None or json.get("pairing_code") is None:
        # Return Bad Request (400) if the request does not contain the required fields
        return jsonify({"error": "Missing 'smartphone-id' or 'pairing_code' in request"}), 400
    
    # The id of the smartphone and the pairing code
    # We already have the pairing code in the database
    # and the id of the pc, so we just need the id of the smartphone
    # to associate the two devices together
    smartphone_id = request.get_json()["smartphone-id"]
    pairing_code = request.get_json()["pairing_code"]
 
    # Find the entry of the pairing code
    entry = pairing_codes.get(pairing_code)
 
    # Bad Request if the pairing code is not found
    if entry is None:
        return jsonify({"accepted": False}), 400
 
    pc_id = entry["pc_id"]
    pc_name = entry["pc_name"]
 
    # Store the devices in the database
    # "partner_device" associates the two devices
    device_database[smartphone_id] = {
        "device_type": "smartphone",
        "partner_device_id": pc_id,
    }
 
    device_database[pc_id] = {
        "device_type": "pc",
        "partner_device_id": smartphone_id,
        "pc_name": pc_name
    }
 
 
    # Return the information about the PC back to the smartphone,
    # as the smartphone is the one that initiated the pairing process
    # and thus called the /setup/pair endpoint
    return jsonify({"accepted": True, "pc_name": pc_name}), 200
 
 
# Called by the PC
@app.route("/2fa/push", methods=["POST"])
def push_2fa():
    """
        Function to create a 2FA request and send it to the smartphone.
        As REST is uni-directional, and we do not use websockets or Server-Sent Events,
        we cannot send a request to the smartphone directly.
        Instead, we will store the 2FA request in the database, and the smartphone
        will pull the request from the backend.
 
        For now, this should suffice, with the downside of the smartphone not
        receiving the 2FA request immediately without action from the user.
 
        @returns 200 OK: ```json
        {
            "comparison_code": "ABCDEF"
        }
        ```
 
        @returns 400 Bad Request
    """
 
    json = request.get_json()
 
    # Get the PC id from the body
    pc_id = json.get("pc-id")
 
    # Return 400 if the PC id is not found
    if pc_id is None:
        return jsonify({"error": "Missing 'pc-id' in request"}), 400
 
    # Get the device from the database
    device = device_database.get(pc_id)
 
    # Return 404 if the device is not found
    if device is None:
        return jsonify({"error": "Device not found"}), 404
 
    # Return 400 if the device is not a PC
    if device["device_type"] != "pc":
        return jsonify({"error": "Device is not a PC"}), 400
 
    # Get the partner device
    partner_device = device_database.get(device["partner_device_id"])
 
    # Return 400 if the partner device is not found, and thus no pairing has been done
    if partner_device is None:
        return jsonify({"error": "Partner device not found, not paired yet."}), 400
 
    # Return 400 if the partner device is not a smartphone
    # This is a security measure to ensure that the 2FA code is only sent to a smartphone
    # But should ideally not happen
    if partner_device["device_type"] != "smartphone":
        return jsonify({"error": "Partner device is not a smartphone"}), 400
 
    # Generate a random 6-digit 2FA comparison code
    comparison_code = ''.join(random.choice(string.ascii_uppercase) for _ in range(6))
 
    # Store the comparison code in the awaiting_2fa database
    awaiting_2fa[device["partner_device_id"]] = {
        "comparison_code": comparison_code,
        "signal": None  # Initialize the signal as None
    }
 
    # Return the comparison code to the PC for it to display
    return jsonify({"comparison_code": comparison_code})
 
 
# Called by the PC to wait for the result of the 2FA request
# This is a blocking function.
# The PC will wait until the smartphone has verified the 2FA request.
#
# The idea is that the PC will call this endpoint after calling /2fa/push
# with a timeout set to a reasonable value.
@app.route("/2fa/await", methods=["POST"])
def pc_await():
    """
        Function to wait for the result of the 2FA request.
        This is a blocking function, and the PC will wait until the smartphone
        has verified the 2FA request.
    """
 
    json = request.get_json()
 
    # Get the PC id from the body
    pc_id = json.get("pc-id")
 
    # Return 400 if the PC id is not found
    if pc_id is None:
        return jsonify({"error": "Missing 'pc-id' in request"}), 400
 
    # Get the device from the database
    device = device_database.get(pc_id)
 
    # Return 404 if the device is not found
    if device is None:
        return jsonify({"error": "Device not found"}), 404
 
    # Return 400 if the device is not a PC
    if device["device_type"] != "pc":
        return jsonify({"error": "Device is not a PC"}), 400
 
    # Return 400 if no 2FA request is awaiting for the smartphone
    awaiting_request = awaiting_2fa.get(device["partner_device_id"])
    if awaiting_request is None:
        return jsonify({"error": "No 2FA request awaiting"}), 400
 
    # Polling loop to wait for the signal
    while True:
        if awaiting_request["signal"] is not None:
            result = awaiting_request["signal"]
            del awaiting_2fa[device["partner_device_id"]]
            return jsonify({"verified": result}), 200
 
        time.sleep(1)  # Sleep for a short duration before polling again
 
 
# Called by the smartphone
@app.route("/2fa/pull")
def pull():
    # Get the smartphone id from the request header
    smartphone_id = request.headers.get("Smartphone-Id")
 
    # Get the device from the database
    device = device_database.get(smartphone_id)
 
    # Return 404 if the device is not found
    if device is None:
        return jsonify({"error": "Device not found"}), 404
 
    # Return 400 if the device is not a smartphone
    if device["device_type"] != "smartphone":
        return jsonify({"error": "Device is not a smartphone"}), 400
 
    # Check if a 2FA request is awaiting for this smartphone id
    awaiting_request = awaiting_2fa.get(smartphone_id)
 
    # Return 404 if no 2FA request is awaiting
    if awaiting_request is None:
        return jsonify({"error": "No 2FA request awaiting"}), 404
 
    # If there is indeed a 2FA request awaiting, return the comparison code to the smartphone
    return jsonify({"comparison_code": awaiting_request["comparison_code"]})
 
 
# Called by the smartphone
@app.route("/2fa/verify", methods=["POST"])
def verify_2fa():
    """
        Function to allow / disallow a 2FA request.
    """
 
    json = request.get_json()
 
    # Get the smartphone id from the request body
    smartphone_id = json.get("smartphone-id")
 
    # Get the comparison code from the request body
    comparison_code = json.get("comparison_code")
 
    # Return 400 if the smartphone id or the comparison code is not found
    if smartphone_id is None or comparison_code is None:
        return jsonify({"error": "Missing 'smartphone-id' or 'comparison_code' in request"}), 400
 
    # Get the device from the database
    device = device_database.get(smartphone_id)
 
    # Return 404 if the smartphone device is not found
    if device is None:
        return jsonify({"error": "Device not found"}), 404
 
    # Return 400 if the device is not a smartphone
    if device["device_type"] != "smartphone":
        return jsonify({"error": "Device is not a smartphone"}), 400
 
    # Check if a 2FA request is awaiting for this smartphone id
    awaiting_request = awaiting_2fa.get(smartphone_id)
 
    # Return 404 if no 2FA request is awaiting
    if awaiting_request is None:
        return jsonify({"error": "No 2FA request awaiting"}), 404
 
    # Check if the comparison code matches
    if awaiting_request["comparison_code"] == comparison_code:
        awaiting_request["signal"] = True  # Signal success to /2fa/await
        return jsonify({"verified": True}), 200
    else:
        awaiting_request["signal"] = False  # Signal failure /2fa/await
        return jsonify({"verified": False}), 200
 
 
if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=6000)