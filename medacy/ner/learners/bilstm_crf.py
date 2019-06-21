import logging
import random

import torch
import torch.optim as optim
import torch.nn as nn
import torch.nn.functional as F

import sys

# Constants
LEARNING_RATE = 0.1
EMBEDDING_DIM = 64
HIDDEN_DIM = 64

class BiLstmCrfNetwork(nn.Module):
    def __init__(self, vocab_size, tagset_size):
        super(BiLstmCrfNetwork, self).__init__()

        self.word_embeddings = nn.Embedding(vocab_size, EMBEDDING_DIM)

        # The LSTM takes word embeddings as inputs, and outputs hidden states
        # with dimensionality hidden_dim.
        self.lstm = nn.LSTM(EMBEDDING_DIM, HIDDEN_DIM, bidirectional=True)

        # The linear layer that maps from hidden state space to tag space
        self.hidden2tag = nn.Linear(HIDDEN_DIM*2, tagset_size)

    def forward(self, sentence):
        embeds = self.word_embeddings(sentence)
        lstm_out, _ = self.lstm(embeds.view(len(sentence), 1, -1))
        tag_space = self.hidden2tag(lstm_out.view(len(sentence), -1))
        tag_scores = F.log_softmax(tag_space, dim=1)
        return tag_scores

class BiLstmCrfLearner:
    model = None
    token_to_index = {}
    tag_to_index = {}

    def __init__(self):
        torch.manual_seed(1)

    def devectorize_tags(self, tags_vectors):
        to_tag = {y:x for x, y in self.tag_to_index.items()}
        tags = []

        for vector in tags_vectors:
            max_value = max(vector)
            index = list(vector).index(max_value)
            tags.append(to_tag[index])
            
        return tags

    def create_index_dictionary(self, sequences):
        to_index = {}
        for sequence in sequences:
            for item in sequence:
                if item not in to_index:
                    to_index[item] = len(to_index)
        return to_index

    def vectorize(self, sequence, to_index):
        # indices = [to_index[w] for w in sequence]
        indices = []

        for item in sequence:
            if item in to_index:
                indices.append(to_index[item])
            else: # TODO Only here for testing until we switch to word embeddings
                indices.append(random.randrange(len(to_index)))

        return torch.tensor(indices, dtype=torch.long)

    def fit(self, x_data, y_data):
        self.token_to_index = self.create_index_dictionary(x_data)
        self.tag_to_index = self.create_index_dictionary(y_data)

        vocab_size = len(self.token_to_index)
        tagset_size = len(self.tag_to_index)
        model = BiLstmCrfNetwork(vocab_size, tagset_size)
        loss_weights = torch.ones(tagset_size) # TODO Change to something else
        # loss_weights[-1] = 0.01 # Reduce weighting towards 'O' label
        loss_function = nn.NLLLoss(loss_weights)
        optimizer = optim.SGD(model.parameters(), lr=LEARNING_RATE)

        for tokens, correct_tags in zip(x_data, y_data):
            # Step 1. Remember that Pytorch accumulates gradients.
            # We need to clear them out before each instance
            optimizer.zero_grad()

            # Step 2. Get our inputs ready for the network, that is, turn them into
            # Tensors of word indices.
            # sentence_in = self.vectorize(sentence, word_to_index)
            # targets = self.vectorize(tags, tag_to_index)
            tokens_vector = self.vectorize(tokens, self.token_to_index)
            correct_tags_vector = self.vectorize(correct_tags, self.tag_to_index)

            # Step 3. Run our forward pass.
            prediction_scores = model(tokens_vector)

            # Step 4. Compute the loss, gradients, and update the parameters by
            #  calling optimizer.step()
            loss = loss_function(prediction_scores, correct_tags_vector)
            loss.backward()
            optimizer.step()

        self.model = model

    def predict(self, sequences):
        if not self.token_to_index:
            raise RuntimeError('There is no token_to_index. Model must not have been fit yet'
                'or was loaded improperly.')
        
        with torch.no_grad():
            predictions = []
            for sequence in sequences:
                vectorized_tokens = self.vectorize(sequence, self.token_to_index)
                tag_scores = self.model(vectorized_tokens)
                predictions.append(self.devectorize_tags(tag_scores))
            # predictions.append(devectorized_tags)

        return predictions
