# How to run the verification on your domain 

1) make a new branch with your domain title (e.g spine-injury)
2) in your branch, in the Alloy_Verifier folder, change the contents of compare.als to match the specifications/protocols of your domain. 
- Make sure to keep the format of the file the same with `module checking` at the top followed by your dependecies, facts, and predicates. 
- After that the file must have a `pred GeneratedPlan {}` predicate. This is where the AI will populate its next suggested steps. Make sure it's empty in the beginning and after each iteration of the plan so the LLM doesn't start with a given plan. 
- At the end of the file, make sure you have 
- `
run {
    GeneratedPlan
    and not ReferenceConstraints
} for 10 Action, 10 Dependency, 1 PatientStatus
`
3) After your compare.als file is consistent with your references, change the prompt variable in main function of pipeline.py (should be line 274). 
   - Make sure the prompt is realistic and something an actual user would give their LLMs to ask for advice. Be intentional with the symptoms you give, the actions you have already taken, and then situation you are in. 
4) run `python pipeline.py` or python3 if that's what you have. 
   - The code should tell you exactly how many iterations of the syntax and logic loop it runs and if it arrives at a safe plan. 
5) After each run of the file, check `pred GeneratedPlan {}` in compare.als to see the plan it generated and sanity check it. 
6) After each un of the file, check the ai_log.txt to see the process of what the LLM was outputting. 
* before running again, either with same prompt or different, make sure to clear out the content inside `pred GeneratedPlan {}` to reset the compare.als file. 

# Comparison 
7) Run the exact same prompt on Claude website or ChatGPT, and see if it outputs a safe plan 
8) Compare the results and the plans generated, with and without our pipeline. 
9) Create a new file in the reuslts folder (where this tutorial is) and give it the same name as your branch. 
10) For each prompt you run, take notes on what you observe, the process of the LLM, and the safety of the plan in the file you created. 