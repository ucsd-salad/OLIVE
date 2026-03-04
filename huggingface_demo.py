"""
Simple HuggingFace LLM demo.

This script:
1. Loads a lightweight language model from HuggingFace
2. Sends a prompt to the model
3. Prints the generated response

Works on CPU or GPU automatically.
"""

from transformers import pipeline
import torch


def load_model(model_name="TinyLlama/TinyLlama-1.1B-Chat-v1.0"):
    """
    Load a text generation pipeline.

    Parameters
    ----------
    model_name : str
        HuggingFace model identifier.

    Returns
    -------
    generator : transformers pipeline
        A text generation pipeline ready to use.
    """

    # This parameter assigns our model to a GPU (if available, meaning it assigns it to the first available GPU on your 
    # machine which will have id = 0 for machines that have NVIDIA CUDA GPUs, or "mps" for machines that have Apple Silicon 
    # GPUs via Metal (MPS)), or assigns to CPU (id = -1) if no GPU is available.
    if torch.cuda.is_available():
        device = 0 # for machines that have NVIDIA CUDA GPUs
    elif torch.backends.mps.is_available():
        device = "mps" # for machines that have Apple Silicon GPUs via Metal (MPS)
    else:
        device = -1 # for CPU

    generator = pipeline(
        task="text-generation",
        model=model_name,
        device=device
    )

    return generator


def generate_response(generator, prompt):
    """
    Feed a prompt to the model and return the generated text.

    Parameters
    ----------
    generator : pipeline
        HuggingFace text-generation pipeline.
    prompt : str
        Input prompt to the model.

    Returns
    -------
    str
        Generated model response.
    """

    # Wrap the prompt in a chat-style format expected by many instruction-tuned models
    formatted_prompt = f"<|user|>\n{prompt}\n<|assistant|>\n"

    # Generate text
    # A token can be a whole word, part of a word, punctuation, or even whitespace depending on the tokenizer.
    # A tokenizer is a tool that converts text into tokens that the model can understand. 
    # The number of tokens in a prompt or response can be different from the number of words or characters, and it depends on the specific tokenizer used by the model.
    outputs = generator(
        formatted_prompt,
        max_new_tokens=200,   # how long the response can be (one token is roughly 4 characters, so 200 tokens is about 800 characters)
        temperature=0.7,      # randomness (0 = deterministic, higher temperature = more random)
        do_sample=True        # whether to sample from the distribution (True) or just take the most likely token (False)
    )

    # Pipeline returns a list of outputs, but we only asked the model to generate one completion/response, so we take the first (and only) completion and extract the generated text.
    # we'd need to specify num_return_sequences > 1 in the generator call if we wanted multiple completions, and then we'd have to loop through the outputs to extract each one.
    response_text = outputs[0]["generated_text"]

    # Remove the prompt portion so we only return the model's completion
    if response_text.startswith(formatted_prompt):
        response_text = response_text[len(formatted_prompt):].strip()

    return response_text


def main():
    """
    Main script execution.
    """

    # Example prompt
    prompt = "Generate a plan for how to acutely treat a broken bone"

    print("Loading model...")

    generator = load_model()

    print("\nSending prompt to model...\n")

    response = generate_response(generator, prompt)

    print("----- MODEL RESPONSE -----\n")
    print(response)


if __name__ == "__main__":
    main()