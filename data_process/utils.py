import json
import re
import string
import pickle
from collections import Counter
from typing import List, Tuple,Optional, Union

import numpy as np
import torch
from sentence_transformers import SentenceTransformer
from sklearn.decomposition import PCA

# Initialize the sentence transformer model
model = SentenceTransformer('all-MiniLM-L6-v2')
from transformers import LongformerModel, LongformerTokenizer

# Initialize model and tokenizer once at module level
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
device="cpu"
MODEL_NAME = "allenai/longformer-base-4096"
tokenizer = LongformerTokenizer.from_pretrained(MODEL_NAME)
model_long = LongformerModel.from_pretrained(MODEL_NAME)
model_long = model_long.to(device)

# File I/O functions
def loadjson(filename: str) -> dict:
    """
    Load data from a JSON file.

    Args:
        filename: Path to the JSON file

    Returns:
        Dictionary containing the loaded JSON data
    """
    with open(filename, 'r', encoding='utf-8') as file:
        data = json.load(file)
    return data


def savejson(data: dict, filename: str) -> None:
    """
    Save data to a JSON file.

    Args:
        data: Dictionary to save
        filename: Path where the JSON file will be saved
    """
    with open(filename, 'w') as json_file:
        json.dump(data, json_file, indent=4)


def loadpkl(filename: str) -> any:
    """
    Load data from a pickle file.

    Args:
        filename: Path to the pickle file

    Returns:
        The unpickled object
    """
    with open(filename, 'rb') as file:
        data = pickle.load(file)
    return data


def savepkl(data: any, filename: str) -> None:
    """
    Save data to a pickle file.

    Args:
        data: Object to save
        filename: Path where the pickle file will be saved
    """
    with open(filename, 'wb') as pkl_file:
        pickle.dump(data, pkl_file)


# Text normalization and evaluation functions
def normalize_answer(s: str, normal_method: str = "") -> str:
    """
    Normalize text for evaluation.

    Args:
        s: String to normalize
        normal_method: Method for normalization ("mc" for multiple choice, "" for standard)

    Returns:
        Normalized string
    """

    def remove_articles(text):
        return re.sub(r'\b(a|an|the)\b', ' ', text)

    def white_space_fix(text):
        return ' '.join(text.split())

    def remove_punc(text):
        exclude = set(string.punctuation)
        return ''.join(ch for ch in text if ch not in exclude)

    def lower(text):
        return text.lower()

    def mc_remove(text):
        a1 = re.findall(r'\(\s*[a-zA-Z]\s*\)', text)
        if len(a1) == 0:
            return ""
        return a1[-1]

    if normal_method == "mc":
        return mc_remove(s)
    return white_space_fix(remove_articles(remove_punc(lower(s))))


def f1_score(prediction: str, ground_truth: str) -> Tuple[float, float, float]:
    """
    Calculate F1 score between prediction and ground truth.

    Args:
        prediction: Predicted text
        ground_truth: Ground truth text

    Returns:
        Tuple of (f1, precision, recall)
    """
    normalized_prediction = normalize_answer(prediction)
    normalized_ground_truth = normalize_answer(ground_truth)

    ZERO_METRIC = (0, 0, 0)

    if normalized_prediction in ['yes', 'no', 'noanswer'] and normalized_prediction != normalized_ground_truth:
        return ZERO_METRIC
    if normalized_ground_truth in ['yes', 'no', 'noanswer'] and normalized_prediction != normalized_ground_truth:
        return ZERO_METRIC

    prediction_tokens = normalized_prediction.split()
    ground_truth_tokens = normalized_ground_truth.split()
    common = Counter(prediction_tokens) & Counter(ground_truth_tokens)
    num_same = sum(common.values())

    if num_same == 0:
        return ZERO_METRIC

    precision = 1.0 * num_same / len(prediction_tokens)
    recall = 1.0 * num_same / len(ground_truth_tokens)
    f1 = (2 * precision * recall) / (precision + recall)

    return f1, precision, recall


def exact_match_score(prediction: str, ground_truth: str, normal_method: str = "") -> bool:
    """
    Check if prediction exactly matches ground truth after normalization.

    Args:
        prediction: Predicted text
        ground_truth: Ground truth text
        normal_method: Method for normalization

    Returns:
        True if exact match, False otherwise
    """
    if normal_method == "mc":
        return ground_truth.strip().lower() in normalize_answer(prediction, normal_method=normal_method).strip().lower()
    return (normalize_answer(prediction, normal_method=normal_method) ==
            normalize_answer(ground_truth, normal_method=normal_method))


def cemf1_score(prediction: str, ground_truth: str):
    norm_prediction = normalize_answer(prediction, normal_method="")
    norm_gt = normalize_answer(ground_truth, normal_method="")
    if norm_prediction == norm_gt or norm_gt in norm_prediction:
        return 1.0
    else:
        return f1_score(prediction=prediction, ground_truth=ground_truth)[0]


def cem_score(prediction: str, ground_truth: str):
    norm_prediction = normalize_answer(prediction, normal_method="")
    norm_gt = normalize_answer(ground_truth, normal_method="")
    if norm_prediction == norm_gt or norm_gt in norm_prediction:
        return 1.0
    else:
        return 0.0



def hellaswag_preprocess(text):
    text = text.strip()
    # NOTE: Brackets are artifacts of the WikiHow dataset portion of HellaSwag.
    text = text.replace(" [title]", ". ")
    text = re.sub("\\[.*?\\]", "", text)
    text = text.replace("  ", " ")
    return text


# Embedding and dimensionality reduction
def reduce_embedding_dim(embed: np.ndarray, dim: int = 50) -> np.ndarray:
    """
    Reduce dimensionality of embeddings using PCA.

    Args:
        embed: Embedding vectors
        dim: Target dimension

    Returns:
        Reduced embeddings
    """
    pca = PCA(n_components=dim)
    reduced_embeddings = pca.fit_transform(embed)
    return reduced_embeddings


def get_longformer_representation(text):
    """
    Get representations of long text using Longformer on CUDA:0 device

    Args:
        text (str): Long text to be represented

    Returns:
        dict: Contains different types of representations (last_hidden_state, pooled_output, all_hidden_states)
    """


    # Set global attention mask - this is a key feature of Longformer
    # We set the [CLS] token to have global attention so it can attend to the entire sequence
    inputs = tokenizer(text, return_tensors="pt", max_length=4096, truncation=True)

    inputs = {k: v.to(device) for k, v in inputs.items()}

    # Create global attention mask - set the first token ([CLS]) to have global attention
    global_attention_mask = torch.zeros(
        inputs["input_ids"].shape,
        dtype=torch.long,
        device=device
    )
    # Set the CLS token to have global attention
    global_attention_mask[:, 0] = 1

    # Get model outputs
    with torch.no_grad():
        outputs = model_long(
            input_ids=inputs["input_ids"],
            attention_mask=inputs["attention_mask"],
            global_attention_mask=global_attention_mask,
            output_hidden_states=True  # Output all hidden states
        )

    # Get different types of representations
    representations = {
        # Last layer hidden states (batch_size, sequence_length, hidden_size)
        "last_hidden_state": outputs.last_hidden_state,

        # [CLS] token representation (commonly used for classification tasks)
        "cls_representation": outputs.last_hidden_state[0, 0, :],

        # All layer hidden states (if needed)
        "all_hidden_states": outputs.hidden_states if hasattr(outputs, "hidden_states") else None
    }

    return representations["cls_representation"]


def get_embedding(instructions: List[str]) -> np.ndarray:
    """
    Get embeddings for a list of texts and optionally reduce dimensions.

    Args:
        instructions: List of texts to embed
        dim: Target dimension for embeddings

    Returns:
        Numpy array of embeddings
    """
    emb_list = model.encode(instructions)
    return emb_list

# this is the code used to evluates generated code against test case 
def evaluate_code(generated_code, test_cases, timeout=5):
    """
    Evaluates generated code against test cases
    
    Args:
        generated_code (str): The code generated by the model
        test_cases (list): List of test case strings (assertions)
        timeout (int): Maximum execution time in seconds
    
    Returns:
        bool: True if all tests pass, False otherwise
    """
    import signal
    
    # Create a safe execution environment
    local_vars = {}
    
    # Define timeout handler
    def timeout_handler(signum, frame):
        raise TimeoutError("Code execution timed out")
    
    try:
        # Set timeout
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(timeout)
        
        # Execute the generated code
        exec(generated_code, {}, local_vars)
        
        # Run test cases
        for test in test_cases:
            exec(test, local_vars)
            
        # If we get here, all tests passed
        return True
        
    except AssertionError:
        # Test failed
        return False
    except Exception as e:
        # Code execution error
        print(f"Error during execution: {str(e)}")
        return False
    finally:
        # Disable the alarm
        signal.alarm(0)


from openai import OpenAI

_cached_client = None


def get_client(
    base_url="",
    api_key="",
    max_retries=2,
    timeout=300
):
    global _cached_client
    if _cached_client is None:
        _cached_client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries
        )
    return _cached_client


def model_prompting(
    llm_model: str,
    prompt: str,
    max_token_num: Optional[int] = 1024,
    temperature: Optional[float] = 0.2,
    top_p: Optional[float] = 0.7,
    stream: Optional[bool] = True,
    base_url="",
    api_key=""
) -> Union[str, None]:
    """
    Get a response from an LLM model using the OpenAI-compatible NVIDIA API.

    Args:
        llm_model: Name of the model to use (e.g., "nvdev/nvidia/llama-3.1-nemotron-70b-instruct")
        prompt: Input prompt text
        return_num: Number of completions to generate
        max_token_num: Maximum number of tokens to generate
        temperature: Sampling temperature
        top_p: Top-p sampling parameter
        stream: Whether to stream the response

    Returns:
        Generated text response (or None if streaming is enabled)
    """
    client = get_client(base_url=base_url, api_key=api_key)
    completion = client.chat.completions.create(
        model=llm_model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_token_num,
        temperature=temperature,
        top_p=top_p,
        stream=stream
    )

    response_text = ""
    for chunk in completion:
        if chunk.choices[0].delta.content is not None:
            response_text += chunk.choices[0].delta.content
    # print(response_text)
    return response_text