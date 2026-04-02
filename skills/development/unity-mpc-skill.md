---
name: "unity-mpc-skill"
description: "Especialista en MCP (Model Context Protocol) para Unity. Configura, conecta y gestiona servidores MCP como Service Provider, analizando documentación para implementar integraciones correctas."
category: "development"
created: "2026-04-01T18:50:18.291377"
---

# Unity MPC Skill

## Overview

This skill enables configuration and management of **Model Context Protocol (MCP)** servers within Unity environments. MCP is an open standard (originally by Anthropic, now community-driven) that allows AI assistants to connect to external data sources and tools through standardized JSON-RPC interfaces.

**When to activate this skill:**
- User mentions "MCP server", "Model Context Protocol", or "MCP client"
- Need to integrate Unity with external AI tools, databases, or APIs via MCP
- Configuring Unity as an MCP client (consumer) or MCP server (provider)
- Troubleshooting MCP connection issues in Unity Editor or Runtime
- Implementing `stdio` or Server-Sent Events (SSE) transport layers in C#

**Scope:** Covers both **Editor tooling** (Unity Editor extensions that connect to MCP servers) and **Runtime applications** (games/apps that consume MCP services), with emphasis on C# implementation patterns, process management, and Unity-specific threading constraints.

---

## Guidelines

### 1. Architecture Decision Framework

**Determine the mode first:**
- **Unity as MCP Client** (most common): Unity connects to external MCP servers (Python, Node.js, etc.) to access tools/resources
- **Unity as MCP Server** (advanced): Unity exposes its internals (Scene hierarchy, AssetDatabase) as MCP resources to external AI clients

**Transport Selection:**
- **Stdio Transport**: For local servers (Python/Node scripts). Use `System.Diagnostics.Process` with redirected streams
- **SSE Transport**: For remote servers or containerized services. Use `UnityEngine.Networking.UnityWebRequest` or `System.Net.Http`

### 2. Implementation Patterns

#### A. Client Initialization (Stdio)
```csharp
using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Threading.Tasks;

public class McpClient : IDisposable
{
    private Process _serverProcess;
    private StreamWriter _stdin;
    private StreamReader _stdout;
    private int _requestId = 0;
    
    public async Task Initialize(string serverCommand, string arguments)
    {
        var psi = new ProcessStartInfo
        {
            FileName = serverCommand,
            Arguments = arguments,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true
        };

        _serverProcess = new Process { StartInfo = psi };
        _serverProcess.Start();
        
        _stdin = _serverProcess.StandardInput;
        _stdout = _serverProcess.StandardOutput;
        
        // Initialize MCP session
        await SendRequest("initialize", new
        {
            protocolVersion = "2024-11-05",
            capabilities = new { },
            clientInfo = new { name = "UnityMCPClient", version = "1.0.0" }
        });
    }
    
    private async Task<JsonElement> SendRequest(string method, object parameters)
    {
        var request = new
        {
            jsonrpc = "2.0",
            id = ++_requestId,
            method,
            @params = parameters
        };
        
        var json = JsonSerializer.Serialize(request);
        await _stdin.WriteLineAsync(json);
        await _stdin.FlushAsync();
        
        // Read response (handle in Unity Main Thread for UI updates)
        var response = await _stdout.ReadLineAsync();
        return JsonSerializer.Deserialize<JsonElement>(response);
    }
    
    public void Dispose()
    {
        _stdin?.Close();
        _serverProcess?.Kill();
        _serverProcess?.Dispose();
    }
}
```

#### B. Unity Main Thread Safety
All MCP responses that interact with Unity API must marshal to main thread:
```csharp
// Using UniTask (recommended)
await UniTask.SwitchToMainThread();
// OR using Unity's MainThreadDispatcher
MainThreadDispatcher.Enqueue(() => {
    // Update Unity objects here
});
```

#### C. Capability Negotiation
Always verify server capabilities before calling tools:
```csharp
public async Task<List<McpTool>> ListTools()
{
    var response = await SendRequest("tools/list", null);
    // Parse and cache available tools
    return ParseTools(response);
}

public async Task<JsonElement> CallTool(string toolName, JsonElement arguments)
{
    return await SendRequest("tools/call", new 
    { 
        name = toolName, 
        arguments = arguments 
    });
}
```

### 3. Server Configuration Patterns

**Configuration File Structure** (mcp-config.json):
```json
{
  "mcpServers": {
    "unity-asset-db": {
      "command": "node",
      "args": ["/path/to/unity-mcp-server/dist/index.js"],
      "env": {
        "UNITY_PROJECT_PATH": "${workspaceFolder}"
      }
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/dir"]
    }
  }
}
```

**Unity-Specific Server Setup:**
When creating Unity-facing MCP servers, ensure they handle these Unity-specific concerns:
- **AssetDatabase paths**: Convert between absolute system paths and `Assets/` relative paths
- **GUID resolution**: Support lookup by Unity GUID, not just filename
- **Scene object references**: Use `GlobalObjectId` for stable references across sessions

### 4. Error Handling & Lifecycle

**Graceful Degradation:**
```csharp
try 
{
    await mcpClient.Initialize("node", "server.js");
}
catch (Exception ex)
{
    Debug.LogWarning($"MCP Server unavailable: {ex.Message}. Falling back to local implementation.");
    // Enable offline mode or local cache
}
```

**Process Cleanup:**
- Always implement `IDisposable`
- Handle Unity Editor playmode changes: Kill servers when exiting Play mode
- Handle domain reloads in Editor: Store process IDs in `EditorPrefs` for cleanup

---

## Examples

### Example 1: Unity Editor Tool with MCP FileSystem Server

**Scenario:** Create an Editor window that uses MCP to read documentation files from disk and generate Unity scripts.

```csharp
using UnityEditor;
using UnityEngine;
using System.Threading.Tasks;

public class McpDocumentationTool : EditorWindow
{
    private McpClient _client;
    private string _filePath = "Docs/api-reference.md";
    private string _generatedCode = "";
    
    [MenuItem("Window/MCP Documentation")]
    static void Init() => GetWindow<McpDocumentationTool>("MCP Docs");

    async void OnEnable()
    {
        _client = new McpClient();
        // Connect to filesystem server
        await _client.Initialize("npx", "-y @modelcontextprotocol/server-filesystem ./Docs");
    }

    void OnGUI()
    {
        _filePath = EditorGUILayout.TextField("Doc Path:", _filePath);
        
        if (GUILayout.Button("Generate Script from Doc"))
        {
            GenerateFromDoc();
        }
        
        EditorGUILayout.TextArea(_generatedCode, GUILayout.ExpandHeight(true));
    }

    async void GenerateFromDoc()
    {
        // Read file via MCP
        var resource = await _client.ReadResource($"file://{_filePath}");
        string content = resource.GetProperty("contents")[0].GetProperty("text").GetString();
        
        // Use another MCP server (e.g., AI code generator) with the content
        var result = await _client.CallTool("generate-unity-script", 
            JsonSerializer.SerializeToElement(new { documentation = content }));
            
        _generatedCode = result.GetProperty
