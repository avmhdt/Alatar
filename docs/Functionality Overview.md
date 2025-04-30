**System Alatar**  
Agent Definition

Overview:

To preface this, this system is called Alatar.

1\. The agent will initially have the main functionalities:

1. Act as a “consultant” where it can perform data analysis tasks (analyze order data, marketing metrics, etc) and compare it with external data (if necessary) (from the internet).  
   1. Example: Alice sends the following prompt: “How can I become more profitable?”  
      * The key here is that Alice asked a relatively vague question. This is because, like most business owners, they are not technical. That being said, the system then sends the prompt to Alatar via a GraphQL query. Alatar then takes this query and processes it using the **Phase 1 Agent Structure**. Following Alice’s query, the system can then first find out what Alice is using for content distribution (let’s say for the sake of the example she is using TikTok). Alatar will then compare her content with that of other, more successful peers in her niche. Following this this, it can perform necessary tasks (internal/external analysis) to best determine how Alice’s business can become more profitable. When Alice receives the suggestions from Alatar, she may ask Alatar to implement said changes, at which point the system will execute said task(s).

2\. Architecture style: monolithic initially to keep our costs down. As for the agent/system/Shopify communication, it should use GraphQL. There should be some middleware for queuing/load balancing.

3\. Working towards complete autonomy is the goal. The vision for this current version is to have a Human-In-The-Loop process where the agent can ask for clarification or elaboration to have the proper context to maintain reliability.

4\. The users will communicate through one of the following channels: 

1. Alatar app on their phone  
2. Shopify Dashboard  
3. Siri  
4. Within specific pages on the Shopify Admin (app extensions)

**Phase 1 Agent Structure:**   
The agent hierarchy for this phase is as follows: 

* Class 1 (Core Agent): Responsible for capturing and interpreting intent from the user’s prompt/query, then creating and assigning appropriate sub-tasks (referred to as Class 1 Tasks) to the relevant sub-agents’ departments.   
  * This agent reviews outputs from Class 2 agents, removes unnecessary, duplicate, or hallucinated information, polishes it, and generates a final output.   
    * Depending on the specific tags that this agent applies to each part of its response, the system will deploy the appropriate “chunks” across the canvas to provide a clear, concise visualization.   
* Class 2 (Department Head): These agents receive Class 1 tasks and determine which Class 3 agents should handle them.   
  * They have the ability to create additional Class 3 tasks if necessary.   
  * After assigning tasks, this agent oversees the progress of each Class 3 agent.   
  * Based on its review, it can send an agent back for revision if needed, allowing up to five errors before aborting.   
  * Once all Class 3 agents have completed their tasks, the Class 2 agent will aggregate, clean, review, tag (if necessary), and send its response to the Class 1 agent.   
* Class 3 (Service Workers): These agents are highly optimized for specific tasks within each department. They handle individual tasks one by one before handing them off to Class 2 for review. 