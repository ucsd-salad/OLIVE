"""
Simple Claude API LLM demo.

This script:
1. Defines a function to call the Claude API and get a response.
2. Defines a function to generate a response from a given prompt.
3. Contains a main function that demonstrates how to use the above functions.
"""

from anthropic import Anthropic

client = Anthropic(api_key="<YOUR_API_KEY>")

def call_claude(prompt, max_new_tokens=200, temperature=0.7):
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
        max_new_tokens=200,   # how long the response can be (one token is roughly 4 characters, so 200 tokens is about 800 characters)
        temperature=0.7       # randomness (0 = deterministic, higher temperature = more random)
    )

    return response_text.strip()

def run_alloy(alloy_code):
    """
    Johnathan's part 
    Runs the given Alloy code and returns (success, output).
 
    success: true if alloy ran without errors, false otherwise 
    output: the raw output/error string from Alloy.
    """
    pass

# Aila's implementation of syntax verifier loop 
def repair_loop(generator, alloy_code, max_attempts=5):
    """
    Given an initial piece of Alloy code, validate it and ask the LLM
    to fix it if there are errors. Repeat until valid or max_attempts reached.
    """
    attempts = 0

    while attempts < max_attempts:
        attempts += 1
        #run the given alloy code and catch the output 
        success, output = run_alloy(alloy_code)

        #if success = true, no error. loop ends and return the code. 
        if success:
            print("Alloy code is compilable.")
            return True, alloy_code

        prompt = (
            f"You are an expert Alloy repair assistant. The following Alloy code has an error:\n\n"
            f"{alloy_code}\n\n"
            f"The error message is:\n\n"
            f"{output}\n\n"
            f"Only make changes based on the error. Return ONLY valid Alloy code. No explanations."
        )

        # set temperature to 0 for deterministic output
        # otherwise, we might get different "repairs" each time we run the loop, which could make it harder to converge on a working solution
        alloy_code = generate_response(prompt, temperature=0) 

    print(f"Failed after {max_attempts} attempts.")
    return False, alloy_code

 

def main():
    """
    Main script execution.
    """

    # Example prompt
    prompt = "Generate a plan for how to acutely treat a broken bone"

    print("\nSending prompt to Claude...\n")

    response = generate_response(prompt)

    print("----- MODEL RESPONSE -----\n")
    print(response)

    # the relevant Alloy plan will be injected into the prompt via a tool call (i.e. the LLM will call a tool that retrieves the Alloy plan from the database and injects it into the prompt)
    # The model will generate a response that is the Alloy candidate plan
    # We need to port Alloy to Python, i.e. be able to feed the model's Alloy candidate plan response from our Python program, into our Alloy model-checking code, to verify the plan's safety and correctness
    # Then, if the plan doesn't verify, I think we we should do a few-shot prompting approach where we feed the model a few examples of plans it generated that failed verification, along with the Alloy counterexamples that explain why they failed, to help the model learn to generate plans that are more likely to verify successfully
    # basically this is a loop where we generate a candidate plan, verify it, and if it fails verification, we feed the model the failed plan and the counterexample, and ask it to generate a new candidate plan, and we repeat until we get a plan that verifies successfully
    # Then, we ask the model to translate the Alloy plan to English and have the human review it


if __name__ == "__main__":
    main()