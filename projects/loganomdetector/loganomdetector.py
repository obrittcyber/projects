import re

def detect_anomalies(log_file):
    with open(log_file, 'r') as file:
        logs = file.readlines()
    
    anomaly_patterns = [
        r'failed login',
        r'error',
        r'unauthorized access',
        r'exception',
        r'critical'
    ]
    
    anomalies = []
    for line in logs:
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in anomaly_patterns):
            anomalies.append(line.strip())
    
    return anomalies

# Example usage
log_file = "system_logs.txt"
anomalies = detect_anomalies(log_file)
print("Detected Anomalies:")
for anomaly in anomalies:
    print(anomaly)
