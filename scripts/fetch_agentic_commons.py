import urllib.request
import json
import os

url = "https://agentic-commons.org/api/v1/projects"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
    
    projects = data.get("items", [])
    
    # Save to data/seed_projects.json
    output_path = os.path.join("data", "seed_projects.json")
    with open(output_path, "w") as f:
        json.dump(projects, f, indent=2)
        
    print(f"Successfully fetched and saved {len(projects)} projects to {output_path}")
except Exception as e:
    print(f"Error fetching projects: {e}")
