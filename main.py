import random
import string
import time

from flask import Flask, Response, jsonify, request

app = Flask(__name__, template_folder='templates')


pairing_codes = {}
device_database = {}
awaiting_2fa = {}


@app.route("/test")
def test():
    return "Hello, World!"


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
            "error": "Missing 'pc-id' or 'pc-name' in headers"
        }
        ```
    """
    pc_id = request.headers.get("Pc-Id")
    pc_name = request.headers.get("Pc-Name")
    if pc_id is None or pc_name is None:
        # Return Bad Request (400) if the request does not contain the required headers
        return Response(status=400, headers={"Error": "Missing 'pc-id' or 'pc-name' in headers"})

    # Generate a random pairing code
    pairing_code = ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8))
    pairing_codes[pairing_code] = {
        "pc_id": pc_id,
        "pc_name": pc_name
    }

    return Response(headers={"Pairing-Code": pairing_code})


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
            "error": "Missing 'smartphone-id' or 'pairing_code' in headers"
        }
        ```
    """
    smartphone_id = request.headers.get("Smartphone-Id")
    pairing_code = request.headers.get("Pairing-Code")
    if smartphone_id is None or pairing_code is None:
        # Return Bad Request (400) if the request does not contain the required headers
        return Response(status=400, headers={"Error": "Missing 'smartphone-id' or 'pairing-code' in headers"})

    # Find the entry of the pairing code
    entry = pairing_codes.get(pairing_code)

    # Bad Request if the pairing code is not found
    if entry is None:
        return Response(status=400, headers={"Accepted": "False"})

    pc_id = entry["pc_id"]
    pc_name = entry["pc_name"]

    # Delete the pairing code from the database
    del pairing_codes[pairing_code]

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
    return Response(headers={"Accepted": "True", "Pc-Name": pc_name})


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
    pc_id = request.headers.get("Pc-Id")

    # Return 400 if the PC id is not found
    if pc_id is None:
        return Response(status=400, headers={"Error": "Missing 'pc-id' in headers"})

    # Get the device from the database
    device = device_database.get(pc_id)

    # Return 404 if the device is not found
    if device is None:
        return Response(status=404, headers={"Error": "Device not found"})

    # Return 400 if the device is not a PC
    if device["device_type"] != "pc":
        return Response(status=400, headers={"Error": "Device is not a PC"})

    # Get the partner device
    partner_device = device_database.get(device["partner_device_id"])

    # Return 400 if the partner device is not found, and thus no pairing has been done
    if partner_device is None:
        return Response(status=400, headers={"Error": "Partner device not found, not paired yet."})

    # Return 400 if the partner device is not a smartphone
    if partner_device["device_type"] != "smartphone":
        return Response(status=400, headers={"Error": "Partner device is not a smartphone"})

    # Generate a random 6-digit 2FA comparison code
    comparison_code = ''.join(random.choice(string.ascii_uppercase) for _ in range(6))

    # Store the comparison code in the awaiting_2fa database
    awaiting_2fa[device["partner_device_id"]] = {
        "comparison_code": comparison_code,
        "signal": None  # Initialize the signal as None
    }

    # Return the comparison code to the PC for it to display
    return Response(headers={"Comparison-Code": comparison_code})


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
    pc_id = request.headers.get("Pc-Id")

    # Return 400 if the PC id is not found
    if pc_id is None:
        return Response(status=400, headers={"Error": "Missing 'pc-id' in headers"})

    # Get the device from the database
    device = device_database.get(pc_id)

    # Return 404 if the device is not found
    if device is None:
        return Response(status=404, headers={"Error": "Device not found"})

    # Return 400 if the device is not a PC
    if device["device_type"] != "pc":
        return Response(status=400, headers={"Error": "Device is not a PC"})

    # Return 400 if no 2FA request is awaiting for the smartphone
    awaiting_request = awaiting_2fa.get(device["partner_device_id"])
    if awaiting_request is None:
        return Response(status=400, headers={"Error": "No 2FA request awaiting"})

    # Polling loop to wait for the signal
    while True:
        if awaiting_request["signal"] is not None:
            result = awaiting_request["signal"]
            del awaiting_2fa[device["partner_device_id"]]
            return Response(headers={"Verified": str(result)})
        
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
        return Response(status=404, headers={"Error": "Device not found"})

    # Return 400 if the device is not a smartphone
    if device["device_type"] != "smartphone":
        return Response(status=400, headers={"Error": "Device is not a smartphone"})

    # Check if a 2FA request is awaiting for this smartphone id
    awaiting_request = awaiting_2fa.get(smartphone_id)

    # Return 404 if no 2FA request is awaiting
    if awaiting_request is None:
        return Response(status=404, headers={"Error": "No 2FA request awaiting"})

    # If there is indeed a 2FA request awaiting, return the comparison code to the smartphone
    return Response(headers={"Comparison-Code": awaiting_request["comparison_code"]})


# Called by the smartphone
@app.route("/2fa/verify", methods=["POST"])
def verify_2fa():
    """
        Function to allow / disallow a 2FA request.
    """
    smartphone_id = request.headers.get("Smartphone-Id")
    comparison_code = request.headers.get("Comparison-Code")

    # Return 400 if the smartphone id or the comparison code is not found
    if smartphone_id is None or comparison_code is None:
        return Response(status=400, headers={"Error": "Missing 'smartphone-id' or 'comparison_code' in headers"})

    # Get the device from the database
    device = device_database.get(smartphone_id)

    # Return 404 if the smartphone device is not found
    if device is None:
        return Response(status=404, headers={"Error": "Device not found"})

    # Return 400 if the device is not a smartphone
    if device["device_type"] != "smartphone":
        return Response(status=400, headers={"Error": "Device is not a smartphone"})

    # Check if a 2FA request is awaiting for this smartphone id
    awaiting_request = awaiting_2fa.get(smartphone_id)

    # Return 404 if no 2FA request is awaiting
    if awaiting_request is None:
        return Response(status=404, headers={"Error": "No 2FA request awaiting"})

    # Check if the comparison code matches
    if awaiting_request["comparison_code"] == comparison_code:
        awaiting_request["signal"] = True  # Signal success to to /2fa/await
        response = Response(headers={"Verified": "True"})
    else:
        awaiting_request["signal"] = False  # Signal failure to /2fa/await
        response = Response(headers={"Verified": "False"})

    # Remove the 2FA request from the database
    del awaiting_2fa[smartphone_id]

    return response


if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=6000)