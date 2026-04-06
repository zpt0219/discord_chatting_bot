# 🏗️ System Architecture Overview

This section visualizes how a message travels through the system and how the overall components are structured.

## 🌊 Happy Path: The "Sense-Think-Act" Sequence

This sequence diagram illustrates exactly how a single user message travels through the system from the moment it is received until the final memory extraction is persisted to disk.

```mermaid
sequenceDiagram
    participant U as 👤 User
    participant B as 🤖 bot.py
    participant A as 🧠 agent.py
    participant R as 🚦 router.py
    participant S as 🛠️ skills/
    participant M as 📂 memory_manager.py

    U->>B: Sends Message
    B->>B: Batch/Queue Items
    B->>B: Acquire Integrity Lock
    B->>A: generate_response()
    A->>M: get_owner_relationship()
    M-->>A: (Identity, Interests, Routine)
    A->>R: get_model_response()
    
    rect rgb(240, 240, 240)
        Note right of R: Model Interaction Loop
        R->>S: execute_skill()
        S-->>R: (Tool Data)
    end

    R-->>A: Final Text Response
    A-->>B: {text, attachment}
    B->>U: Sends Discord Reply
    
    B->>A: extract_and_update_memory()
    A->>M: add_categorized_facts()
    A->>M: add_key_memory()
    B->>M: save()
    M->>M: Atomic Disk Write
    B->>B: Release Integrity Lock
```

---

## 🏛️ High-Level Component Structure

```mermaid
graph TD
    User["👤 Discord User"] --> Bot["🤖 bot.py (Discord Wrapper)"]
    
    subgraph "Core Orchestration"
        Bot --> MQ["📥 Message Queue & Joiner"]
        MQ --> Agent["🧠 agent.py (Context & Prompt)"]
    end
    
    subgraph "Model Orchestration (Tiered Router)"
        Agent --> Router["⚡ models/router.py"]
        Router --> Llama["🏠 Tier 1: Local Llama.cpp"]
        Llama -- "Failover" --> Claude["☁️ Tier 2: Anthropic Claude"]
        Claude -- "Failover" --> GPT4["🔊 Tier 3: OpenAI GPT-4o"]
    end
    
    subgraph "Capabilities (LLM Tools)"
        Llama & Claude & GPT4 --> Skills["🛠️ skills/__init__.py"]
        Skills --> News["📰 News"]
        Skills --> Reminders["⏰ Reminders"]
        Skills --> Search["🔍 Web Search"]
        Skills --> LinkReader["🔗 URL Reader"]
        Skills --> Weather["⛅ Weather"]
        Skills --> Time["🕒 Time"]
        Skills --> Identity["🎭 Identity (Portrait)"]
        Skills --> Brain["🧠 Memory Profile"]
    end
    
    subgraph "Perception (Input Processing)"
        Bot --> Vision["👀 Vision (Images)"]
        Vision --> Agent
    end
    
    subgraph "State & Memory"
        Agent --> Memory["📂 memory_manager.py"]
        Memory --> Data[("👤 owner_relationship.json")]
        
        subgraph "Fact Categories"
            Data --> ID["Identity"]
            Data --> INT["Interests"]
            Data --> PREF["Preferences"]
            Data --> KM["🧠 Key Memories"]
        end
        
        Bot --> BG["🔄 Background Tasks"]
        BG --> RemLoop["🔔 Reminder Loop"]
        BG --> Proactive["📡 Proactive Loop"]
        BG --> Reflection["🧠 AI Reflection"]
        
        Reflection --> Router
        Router -.-> |"Update Categories"| Memory
        
        RemLoop & Proactive --> Memory
    end
    
    Skills --> Agent
    Agent --> Bot
    Bot --> User
```

### 🗝️ Key Components

| Component | Responsibility |
| :--- | :--- |
| **`bot.py`** | **Ingestion & UI**: Handles Discord connections, message queuing, and downloads vision attachments. Protects memory integrity with a **psutil-based singleton lock**. Runs proactive loops. |
| **`agent.py`** | **Context & Multi-modal Orchestration**: Formats the system prompt by combining **Identity Traits**, **Categorized Facts**, and **Recent Raw Exchanges** for immediate context. |
| **`models/router.py`** | **The Switchboard**: Dynamically selects the best model (Local -> OpenAI -> Claude) based on complexity and vision needs. Handles failovers and tool execution. |
| **`memory_manager.py`** | **Atomic Persistence**: Manages JSON knowledge stores and performs **async, atomic disk writes** via temp-and-swap to prevent data corruption. |
| **`skills/`** | A modular directory with **8+ core tools**: Time, Weather, Web Search, News, Reminders, Brain Profile, Identity Moods, and Link Reader. |
| **`models/`** | Specific API wrappers and vision logic. Each provider (Claude, OpenAI, Local) implements its own extraction tool schema. |
| **`prompts.py`** | Stores the core personality (System Prompt), proactive logic, and the background memory extraction template. |

### 🔄 The Message Flow

1.  **Ingest**: `bot.py` batches rapid user messages into a single thought session.
2.  **Context**: `agent.py` pulls categorized memories and injects the **Last 5 Raw Turns** into the prompt.
3.  **Think**: `router.py` selects the best model tier (Local -> Cloud) for the request complexity. 
4.  **Act**: The LLM executes **Skills**. Attachment-heavy tools (like Portraits) use a request-scoped `attachments_list` to handle files safely in concurrent environments.
5.  **Reflect**: After each reply, a background task performs **AI Reflection**. It extracts new facts and updates the categorized store.
6.  **Commit**: The `MemoryManager` flushes updates atomically to disk while still under the processing lock.
