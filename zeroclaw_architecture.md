# ZeroClaw: Low-Level Binary Memory & Layer Architecture

ZeroClaw is a high-performance, Rust-based AI agent framework designed for **minimal resource consumption** and **persistent context accumulation**. Unlike heavy, always-on frameworks (like OpenClaw or LangChain), ZeroClaw operates as a "Stateless Idle Brain" that wakes up on trigger, processes context from low-level binary storage, and returns to a deep sleep state (~5MB RAM).

---

## 1. The Low-Level Binary Storage Engine

ZeroClaw replaces heavy, RAM-consuming database servers with **Direct Binary Mapping**. Instead of keeping your memory in a running process, it stores it as highly optimized binary files on your disk.

### **Key Binary Technologies:**
*   **Vector Binary (Binary Quantization):** Converts complex `float32` embeddings (meanings) into compact bit-streams. This allows for hardware-level XOR-based similarity searching.
*   **Zero-Copy Deserialization (Bincode/Serde):** Uses Rust's memory safety to map binary files directly into address space (`mmap`). ZeroClaw can read 100MB of history without "loading" it into RAM.
*   **SQLite (Native Binary Mode):** Stores structured session logs and metadata in a single, local binary file that requires zero background resources.

---

## 2. The 5-Layer Memory Architecture

ZeroClaw maintains "Accumulated Context" by organizing data into five distinct layers. When a trigger occurs, it selectively pulls data from these layers to "remind" the LLM of your preferences.

### **Layer 1: Session Memory (LSM)**
*   **State:** Volatile (RAM)
*   **Purpose:** Immediate context of the active conversation.
*   **Logic:** Stores the last 5–10 messages to ensure the agent understands "it" or "that" in a sentence. Cleared immediately when the agent returns to sleep.

### **Layer 2: Cross-Session Recall (Semantic Memory)**
*   **State:** Persistent (Vector Binary File)
*   **Purpose:** Long-term "Meaning" recall.
*   **Logic:** Uses the **Vector Binary** engine to find past interactions similar to your current command. 
*   **Example:** You say *"Apply like we did for that Python role last week."* ZeroClaw wakes up, searches the binary vector index, finds the "Python role" context, and injects it into the prompt.

### **Layer 3: Durable Knowledge (The "PARA" Layer)**
*   **State:** Persistent (Markdown/Protobuf)
*   **Purpose:** Hard facts and system rules.
*   **Logic:** Stores your Resume, Contact Info, and explicit instructions (e.g., *"Always apply in Russian"*). 
*   **Format:** Uses **Protobuf** for ultra-fast, structured binary retrieval of your personal profile.

### **Layer 4: Operational Audit Logs**
*   **State:** Persistent (Append-only Binary)
*   **Purpose:** Success/Failure tracking.
*   **Logic:** Tracks every `@username` contacted and every PDF generated. This prevents AIHawk from accidentally double-applying to the same recruiter.

### **Layer 5: Gigabrain (Pre-prompt Middleware)**
*   **State:** Logic (Computed on Wake-up)
*   **Purpose:** Context Assembly.
*   **Logic:** This is the "Brain" logic. Within **10ms of a trigger**, it searches Layers 2, 3, and 4, assembles a "Context Packet," and sends it to the LLM. It ensures the AI doesn't have "dementia" despite being offline 99% of the time.

---

## 3. The "Deep Sleep" Lifecycle

1.  **Idle State:** ZeroClaw process is parked. **Usage: ~5MB RAM, 0% CPU.**
2.  **Trigger Event:** A command arrives (CLI, Webhook, or Message).
3.  **Binary Wake-up:** Rust runtime starts (~10ms). Maps the Binary Memory files.
4.  **Context Pull:** Selects relevant bits from the 5 Layers.
5.  **Action:** Fires the POST request to the **AIHawk Webhook**.
6.  **Archive & Sleep:** Writes the new interaction to the Binary Log and vanishes from RAM.

---

## 4. Comparison Summary

| Feature | Standard Agent (OpenClaw) | **ZeroClaw (The Idle Brain)** |
| :--- | :--- | :--- |
| **Memory Format** | JSON / Float Vectors | **Binary Bit-streams / Protobuf** |
| **Persistence** | Running DB Server | **Flat Binary Files (mmap)** |
| **Idle Usage** | ~300MB - 1GB RAM | **~5MB RAM** |
| **Context** | "Always On" | **"On-Demand Recall"** |

**Verdict:** ZeroClaw is the only framework that provides **Accumulated Context** (Deep Memory) without the **Resource Tax** (High RAM) of a traditional AI agent.
