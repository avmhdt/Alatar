import requests
import json

def test_graphql_direct():
    url = "http://localhost:8000/graphql-direct"
    payload = {"query": "{ hello }"}
    
    try:
        response = requests.post(url, json=payload)
        print("Status Code:", response.status_code)
        print("Response:", response.text)
        
        if response.status_code == 200:
            print("Success! GraphQL Direct endpoint is working.")
        else:
            print("Error! GraphQL Direct endpoint returned an error.")
    except Exception as e:
        print("Exception:", e)

def test_graphql_standalone():
    url = "http://localhost:8000/graphql-standalone"
    payload = {"query": "{ hello }"}
    
    try:
        response = requests.post(url, json=payload)
        print("Status Code:", response.status_code)
        print("Response:", response.text)
        
        if response.status_code == 200:
            print("Success! GraphQL Standalone endpoint is working.")
        else:
            print("Error! GraphQL Standalone endpoint returned an error.")
    except Exception as e:
        print("Exception:", e)

def test_graphql_standard():
    url = "http://localhost:8000/graphql"
    payload = {"query": "{ hello }"}
    
    try:
        response = requests.post(url, json=payload)
        print("Status Code:", response.status_code)
        print("Response:", response.text)
        
        if response.status_code == 200:
            print("Success! GraphQL standard endpoint is working.")
        else:
            print("Error! GraphQL standard endpoint returned an error.")
    except Exception as e:
        print("Exception:", e)

if __name__ == "__main__":
    print("Testing GraphQL Direct endpoint...")
    test_graphql_direct()
    
    print("\nTesting GraphQL Standalone endpoint...")
    test_graphql_standalone()
    
    print("\nTesting standard GraphQL endpoint...")
    test_graphql_standard() 