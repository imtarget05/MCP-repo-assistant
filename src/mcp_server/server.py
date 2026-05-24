import os
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from github import Github
import logging

# Load environment variables
load_dotenv()

from typing import Any, Dict, List, Optional

# Initialize GitHub client
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
g = Github(GITHUB_TOKEN)

# Initialize FastMCP server
mcp = FastMCP("GitHub Repo Assistant")

import asyncio

@mcp.tool()
async def get_repository_info(repo_name: str) -> Dict[str, Any]:
    """Get detailed information about a GitHub repository.
    
    Args:
        repo_name: Full name of the repo (e.g., 'owner/repo')
    """
    try:
        repo = await asyncio.to_thread(g.get_repo, repo_name)
        
        # Helper to fetch repo details in thread
        def fetch_details(r):
            return {
                "name": r.full_name,
                "description": r.description,
                "stars": r.stargazers_count,
                "forks": r.forks_count,
                "open_issues": r.open_issues_count,
                "language": r.language,
                "topics": r.get_topics(),
                "default_branch": r.default_branch,
                "created_at": str(r.created_at),
                "updated_at": str(r.updated_at),
            }
        
        return await asyncio.to_thread(fetch_details, repo)
    except Exception as e:
        return {"error": f"Error fetching repo info: {str(e)}"}

@mcp.tool()
async def search_repo(repo_name: str, query: str):
    """Search for code or files within a GitHub repository.
    
    Args:
        repo_name: Full name of the repo (e.g., 'owner/repo')
        query: Search query string
    """
    try:
        def do_search():
            results = g.search_code(f"repo:{repo_name} {query}")
            items = []
            for file in results[:10]:
                items.append({"path": file.path, "url": file.html_url})
            return items
            
        return await asyncio.to_thread(do_search)
    except Exception as e:
        return f"Error searching repo: {str(e)}"

@mcp.tool()
async def read_file(repo_name: str, file_path: str):
    """Read the content of a specific file in a GitHub repository.
    
    Args:
        repo_name: Full name of the repo (e.g., 'owner/repo')
        file_path: Path to the file within the repository
    """
    try:
        repo = await asyncio.to_thread(g.get_repo, repo_name)
        content = await asyncio.to_thread(repo.get_contents, file_path)
        return content.decoded_content.decode("utf-8")
    except Exception as e:
        return f"Error reading file: {str(e)}"

@mcp.tool()
async def summarize_architecture(repo_name: str):
    """Analyze the repository structure to summarize its architecture.
    
    Args:
        repo_name: Full name of the repo (e.g., 'owner/repo')
    """
    try:
        repo = await asyncio.to_thread(g.get_repo, repo_name)
        contents = await asyncio.to_thread(repo.get_contents, "")
        structure = [c.path for c in contents]
        return f"Repository '{repo_name}' top-level structure: {', '.join(structure)}"
    except Exception as e:
        return f"Error summarizing architecture: {str(e)}"

@mcp.tool()
async def review_pull_request(repo_name: str, pr_number: int):
    """Review code changes in a specific Pull Request.
    
    Args:
        repo_name: Full name of the repo (e.g., 'owner/repo')
        pr_number: The ID of the PR to review
    """
    try:
        repo = await asyncio.to_thread(g.get_repo, repo_name)
        pr = await asyncio.to_thread(repo.get_pull, pr_number)
        files = await asyncio.to_thread(pr.get_files)
        
        def process_files(f_list):
            review_data = []
            for file in f_list:
                review_data.append({
                    "filename": file.filename,
                    "status": file.status,
                    "additions": file.additions,
                    "deletions": file.deletions,
                    "patch": getattr(file, "patch", "")
                })
            return review_data
            
        return await asyncio.to_thread(process_files, files)
    except Exception as e:
        return f"Error reviewing PR: {str(e)}"

@mcp.tool()
async def create_github_issue(repo_name: str, title: str, body: str):
    """Create a new issue in a GitHub repository.
    
    Args:
        repo_name: Full name of the repo (e.g., 'owner/repo')
        title: Issue title
        body: Issue description/content
    """
    try:
        repo = await asyncio.to_thread(g.get_repo, repo_name)
        issue = await asyncio.to_thread(repo.create_issue, title=title, body=body)
        return {"number": issue.number, "url": issue.html_url}
    except Exception as e:
        return f"Error creating issue: {str(e)}"

import httpx

@mcp.tool()
async def trigger_n8n_workflow(webhook_url: str, payload: dict):
    """Trigger an n8n workflow via a webhook URL.
    
    Args:
        webhook_url: The full n8n webhook URL
        payload: A dictionary containing the data to send to the workflow
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(webhook_url, json=payload)
            response.raise_for_status()
            return f"n8n workflow triggered successfully. Status: {response.status_code}"
    except Exception as e:
        return f"Error triggering n8n workflow: {str(e)}"

if __name__ == "__main__":
    mcp.run()
