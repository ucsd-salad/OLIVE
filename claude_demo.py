"""
Simple Claude API LLM demo.

This script:
1. Defines a function to call the Claude API and get a response.
2. Defines a function to generate a response from a given prompt.
3. Contains a main function that demonstrates how to use the above functions.
"""

# have to run git submodule update --init --recursive first 

from anthropic import Anthropic
from dotenv import load_dotenv
import os
import subprocess

BASE = os.path.dirname(os.path.abspath(__file__))
classpath = f"{BASE}/AlloyCommandline:{BASE}/AlloyCommandline/alloy4.2.jar"

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def call_claude(prompt, max_new_tokens=4000, temperature=0.7):
    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=max_new_tokens, # how long the response can be (one token is roughly 4 characters, so 200 tokens is about 800 characters)
        temperature=temperature, # randomness (0 = deterministic, higher temperature = more random)
        messages=[
            {"role": "user", "content": prompt}
        ],
    )
    return message.content[0].text


def generate_response(prompt, temperature=0.7):
    """
    Feed a prompt to the model and return the generated text.

    Parameters
    ----------
    prompt : str
        Input prompt to the model.
    temperature : float, optional
        Sampling temperature for response generation (default is 0.7).

    Returns
    -------
    str
        Generated model response.
    """

    # Generate text
    # A token can be a whole word, part of a word, punctuation, or even whitespace depending on the tokenizer.
    # A tokenizer is a tool that converts text into tokens that the model can understand. 
    # The number of tokens in a prompt or response can be different from the number of words or characters, and it depends on the specific tokenizer used by the model.
    response_text = call_claude(
        prompt,
        max_new_tokens=1000,   # how long the response can be (one token is roughly 4 characters, so 200 tokens is about 800 characters)
        temperature=0.7       # randomness (0 = deterministic, higher temperature = more random)
    )

    return response_text.strip()

def save_alloy_to_file(alloy_code, output_path="generated_model.als"):
    with open(output_path, "w") as f:
        f.write(alloy_code)
    return output_path

import os
import subprocess

BASE = os.path.dirname(os.path.abspath(__file__))
JAVA_DIR = os.path.join(BASE, "AlloyCommandline")

JAR = os.path.join(JAVA_DIR, "alloy4.2.jar")
JAVA_FILE = os.path.join(JAVA_DIR, "AlloyCommandline.java")
CLASS_FILE = os.path.join(JAVA_DIR, "AlloyCommandline.class")


def run_alloy(alloy_code_path):
    print(f"Running Alloy code from {alloy_code_path}...")

    alloy_code_path = os.path.abspath(alloy_code_path)

    # --- compile if needed: generate the .class files ---
    if not os.path.exists(CLASS_FILE):
        print("Compiling AlloyCommandline.java...")

        compile_cmd = [
            "javac",
            "-cp",
            "alloy4.2.jar",
            "-sourcepath",
            "",
            "AlloyCommandline.java"
        ]

        compile = subprocess.run(
            compile_cmd,
            cwd=JAVA_DIR,
            capture_output=True,
            text=True
        )

        if compile.returncode != 0:
            return False, "Compilation failed:\n" + compile.stderr

    # --- run the alloy file---
    run_cmd = [
        "java",
        "-cp",
        ".:alloy4.2.jar",
        "AlloyCommandline",
        alloy_code_path
    ]

    result = subprocess.run(
        run_cmd,
        cwd=JAVA_DIR,
        capture_output=True,
        text=True
    )
    output = result.stdout + result.stderr

    # --- catch outputs of the terminal ---
    success = (
        result.returncode == 0
        and "Syntax error" not in output
        and "File cannot be found" not in output
    )

    #couldn't run  
    if result.returncode != 0:
        status = "ERROR"
    #syntax error  
    elif "Syntax error" in output:
        status = "SYNTAX ERROR"
    #no instance found (inconsistent)
    elif "No instance" in output or "Inconsistent" in output:
        status = "INCONSISTENT" # -- this is what we want for compare.als 
    #consistent
    elif "Predicate is consistent" in output or "Instance found" in output:
        status = "CONSISTENT" 
    #no counter example
    elif "No counterexample found" in output:
        status = "NO COUNTEREXAMPLE"
    else:   
        status = "NA"

    return success, output, status


# Aila's implementation of syntax verifier loop 
def repair_syntax_loop(alloy_code_path, max_attempts=5):
    """
    Given an initial piece of Alloy code, validate it and ask the LLM
    to fix it if there are errors. Repeat until valid or max_attempts reached.
    """
    attempts = 0
    output_path = "Alloy_Verifier/generated.als"

    while attempts < max_attempts:
        print(f"Syntax Repair Attempt {attempts + 1} of {max_attempts}...")
        attempts += 1
        #run the given alloy code and catch the output 
        success, output_logs, output_status = run_alloy(alloy_code_path)
        print("Alloy output logs:")
        print(output_logs)
        

        #if success = true, no error. loop ends and return the code. 
        if success:
            print("Alloy code is compilable.")
            print("Alloy status:")
            print(output_status)
            return True, alloy_code_path, output_logs

        # read the Alloy file
        with open(alloy_code_path, "r") as f:
            alloy_code = f.read()

        prompt = (
            f"You are an expert Alloy repair assistant. The following Alloy code has an error:\n\n"
            f"{alloy_code}\n\n"
            f"The error message is:\n\n"
            f"{output_logs}\n\n"
            f"Only make changes based on the error. Return ONLY valid Alloy code. No explanations."
        )

        # set temperature to 0 for deterministic output
        # otherwise, we might get different "repairs" each time we run the loop, which could make it harder to converge on a working solution
        gen_alloy_code = generate_response(prompt, temperature=0) 
        alloy_code_path = save_alloy_to_file(gen_alloy_code, output_path=output_path)

    print("Failed after {max_attempts} attempts.")
    return False, output_path, output_logs

def repair_logic_loop(alloy_code_path, max_attempts=5):
    """
    Similar to the syntax repair loop, but focused on logical errors (e.g., not consistent with specification)
    The prompt would need to be adjusted to provide information about the logical errors or counterexamples.
    """

    attempts = 0
    output_path = "Alloy_Verifier/compare.als"  # keep overwriting same file if you want

    while attempts < max_attempts:
        print(f"Logic Repair Attempt {attempts + 1}/{max_attempts}")
        attempts += 1

        success, output_logs, status = run_alloy("Alloy_Verifier/compare.als")

        print("Alloy output:")
        print(output_logs)
        print("Status:", status)

        # generated.als is and consistent with the reference constraints 
        if status == "INCONSISTENT":
            return True, output_path, output_logs

        # generated.als is NOT consistent
        with open("Alloy_Verifier/compare.als", "r") as f:
            compare_code = f.read()

        prompt = f"""
        You are an expert Alloy repair assistant.

        You are given an Alloy file that performs a correctness check. The current GeneratedPlan 
        is violating reference constraints, which means that the plan is not consistent with the specification. 

        IMPORTANT RULE:
        - You are ONLY allowed to modify the predicate: GeneratedPlan {{ ... }}
        - You must NOT modify:
            - ReferenceConstraints
            - run statements
            - module declarations
            - any other part of the file

        GOAL:
        Fix GeneratedPlan so that it does NOT allow any behavior that violates reference constatins.

        CURRENT Alloy code:
        {compare_code}

        Alloy output:
        {output_logs}

        Return ONLY the corrected Alloy code. No explanations.
        """

        gen_code = generate_response(prompt, temperature=0)

        with open("Alloy_Verifier/compare.als", "w") as f:
            f.write(gen_code)

    print("Logic failed after max attempts.")
    return False, alloy_code_path, output_logs
   

def main():
    """
    Main script execution.
    """

    # Example prompt
    # prompt = "Generate a plan for how to acutely treat a broken bone"

    # print("\nSending prompt to Claude...\n")

    # response = generate_response(prompt)


    # implementing the loop 
    # 1) save the response to .als file 
    # alloy_path = save_alloy_to_file(response, output_path="Alloy_Verifier/generated.als")
    # 2) pass path to loop verifier 
    result_bool, alloy_code_path, output_logs = repair_syntax_loop('Alloy_Verifier/generated.als')

    # print("----- MODEL RESPONSE -----\n")
    # print('response')

    print("---the generated plan was compilable? ")
    print(result_bool)

    print("---the generated plan is stored in ")
    print(alloy_code_path)

    print("---output logs ---")
    print(output_logs)

    # 3) if the code is compilable, then run compare.als
    logic_bool, logic_code_path, logic_output_logs = repair_logic_loop('Alloy_Verifier/compare.als')
    if logic_bool:
        print("No counterexample found → model is consistent with reference.")
        print("Safe plan stored in", logic_code_path)
        print("Safe plan Alloy output logs:", logic_output_logs)
    else: 
        print("Counterexample found → model is NOT consistent with reference after multiple attempts.")
        print("Generated UNSAFE plan stored in", logic_code_path)
        print("Generated UNSAFE plan Alloy output logs:", logic_output_logs)



    # the relevant Alloy plan will be injected into the prompt via a tool call (i.e. the LLM will call a tool that retrieves the Alloy plan from the database and injects it into the prompt)
    # The model will generate a response that is the Alloy candidate plan
    # We need to port Alloy to Python, i.e. be able to feed the model's Alloy candidate plan response from our Python program, into our Alloy model-checking code, to verify the plan's safety and correctness
    # Then, if the plan doesn't verify, I think we we should do a few-shot prompting approach where we feed the model a few examples of plans it generated that failed verification, along with the Alloy counterexamples that explain why they failed, to help the model learn to generate plans that are more likely to verify successfully
    # basically this is a loop where we generate a candidate plan, verify it, and if it fails verification, we feed the model the failed plan and the counterexample, and ask it to generate a new candidate plan, and we repeat until we get a plan that verifies successfully
    # Then, we ask the model to translate the Alloy plan to English and have the human review it

if __name__ == "__main__":
    main()