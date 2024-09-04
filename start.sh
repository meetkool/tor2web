#!/bin/bash

echo "Starting Tor..."
tor &
TOR_PID=$!

# Wait for Tor to be ready
echo "Waiting for Tor to be ready..."
for i in {1..30}; do
    if /bin/nc -z localhost 9050; then
        echo "Tor is ready"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "Tor failed to start after 30 seconds"
        exit 1
    fi
    sleep 1
    echo "Still waiting for Tor..."
done

# Check if Tor is still running
if ! kill -0 $TOR_PID 2>/dev/null; then
    echo "Tor process has died"
    exit 1
fi

# Display Tor version and check if it's running
tor --version
ps aux | grep tor

# Test Tor connection
echo "Testing Tor connection..."
curl --socks5 localhost:9050 --socks5-hostname localhost:9050 -s https://check.torproject.org/ | grep -q "Congratulations. This browser is configured to use Tor."
if [ $? -eq 0 ]; then
    echo "Tor is working correctly"
else
    echo "Tor is not working correctly"
    exit 1
fi

# Start the Python app
python app.py
