import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import spacy
from spacy.gold import biluo_tags_from_offsets
from medacy.data import Dataset
from medacy.tools import Annotations

import sys

# Constants
SEGMENT_SIZE = 100

class LSTMTagger(nn.Module):
    def __init__(self, embedding_dim, hidden_dim, vocab_size, tagset_size, bidirectional):
        super(LSTMTagger, self).__init__()
        self.hidden_dim = hidden_dim

        self.word_embeddings = nn.Embedding(vocab_size, embedding_dim)

        # The LSTM takes word embeddings as inputs, and outputs hidden states
        # with dimensionality hidden_dim.
        self.lstm = nn.LSTM(embedding_dim, hidden_dim, bidirectional=bidirectional)

        # The linear layer that maps from hidden state space to tag space
        self.hidden2tag = nn.Linear(hidden_dim, tagset_size)

    def forward(self, sentence):
        embeds = self.word_embeddings(sentence)
        lstm_out, _ = self.lstm(embeds.view(len(sentence), 1, -1))
        tag_space = self.hidden2tag(lstm_out.view(len(sentence), -1))
        tag_scores = F.log_softmax(tag_space, dim=1)
        return tag_scores

class PytorchModel:
    # Properties
    model = None
    labels = []
    word_to_index = {}
    tag_to_index = {}

    def __init__(self, bidirectional=False):
        self.bidirectional = bidirectional

        torch.manual_seed(1)

    def vectorize(self, sequence, to_index):
        indexes = [to_index[w] for w in sequence]
        return torch.tensor(indexes, dtype=torch.long)

    def devectorize(self, vectors, to_index):
        to_tag = {y:x for x, y in to_index.items()}
        tags = []

        for vector in vectors:
            max_value = max(vector)
            index = list(vector).index(max_value)
            tags.append(to_tag[index])
            
        return tags

    def get_segments(self, source):
        segments = []

        for i in range(0, len(source), SEGMENT_SIZE):
            segments.append(source[i:i + SEGMENT_SIZE])

        return segments

    def get_training_data(self, dataset):
        labels = dataset.get_labels()
        labels.add('O')
        training_data = dataset.get_training_data('pytorch')

        word_to_index = {}
        for sent, tags in training_data:
            for word in sent:
                if word not in word_to_index:
                    word_to_index[word] = len(word_to_index)

        tag_to_index = {}

        for label in labels:
            tag_to_index[label] = len(tag_to_index)

        preprocessed_data = []

        for document, tags in training_data:
            sentences = self.get_segments(document)
            tag_segments = self.get_segments(tags)

            for i in range(len(sentences)):
                preprocessed_data.append((sentences[i], tag_segments[i]))

        self.labels = labels
        self.word_to_index = word_to_index
        self.tag_to_index = tag_to_index

        return preprocessed_data

    def fit(self, dataset, epochs=30):
        if not isinstance(dataset, Dataset):
            raise TypeError("Must pass in an instance of Dataset containing your training files")

        training_data = self.get_training_data(dataset)

        word_to_index = self.word_to_index
        tag_to_index = self.tag_to_index

        # These will usually be more like 32 or 64 dimensional.
        # We will keep them small, so we can see how the weights change as we train.
        EMBEDDING_DIM = 64
        HIDDEN_DIM = 64

        model = LSTMTagger(EMBEDDING_DIM, HIDDEN_DIM, len(word_to_index), len(tag_to_index), self.bidirectional)
        loss_weights = torch.ones(len(tag_to_index))
        # loss_weights[0] = 0.1 # Reduce weighting towards 'O' label
        loss_function = nn.NLLLoss(loss_weights)
        optimizer = optim.SGD(model.parameters(), lr=0.1)

        for epoch in range(epochs):
            print('Epoch %d' % epoch)
            losses = []
            i = 0
            for sentence, tags in training_data:
                # Step 1. Remember that Pytorch accumulates gradients.
                # We need to clear them out before each instance
                optimizer.zero_grad()

                # Step 2. Get our inputs ready for the network, that is, turn them into
                # Tensors of word indices.
                sentence_in = self.vectorize(sentence, word_to_index)
                targets = self.vectorize(tags, tag_to_index)

                # Step 3. Run our forward pass.
                tag_scores = model(sentence_in)

                # Step 4. Compute the loss, gradients, and update the parameters by
                #  calling optimizer.step()
                loss = loss_function(tag_scores, targets)
                loss.backward()
                optimizer.step()
                if i % 100 == 0:
                    print(loss)
                i += 1
                losses.append(loss)

            average_loss = sum(losses) / len(losses)
            print('AVG LOSS: %f' % average_loss)

        # See what the scores are after training
        with torch.no_grad():
            inputs = self.vectorize(training_data[0][0], word_to_index)
            print(inputs)
            tag_scores = model(inputs)

            print('SECOND TAG SCORES')
            print(tag_scores)
            print('----TRAINING------')
            print(training_data[0][1])
            print('----PREDICTION----')
            devectorized_tag_scores = self.devectorize(tag_scores, tag_to_index)
            print(devectorized_tag_scores)
            length = len(tag_scores)

            f1_scores = []

            for label in self.labels:
                false_positives = 0
                true_positives = 0
                false_negatives = 0
                true_negatives = 0

                for i in range(length):
                    prediction = devectorized_tag_scores[i]
                    correct_tag = training_data[0][1][i]

                    if correct_tag == label:
                        if prediction == label:
                            true_positives += 1
                        else:
                            false_negatives += 1
                    else:
                        if prediction == label:
                            false_positives += 1
                        else:
                            true_negatives += 1

                precision = true_positives / (true_positives + false_positives + 0.00001)
                recall = true_positives / (true_positives + false_negatives + 0.00001)
                f1 = 2 * ((precision * recall) / (precision + recall + 0.00001))
                f1_scores.append(f1)
                print('Sentence 0 %s Scores:' % label)
                print('Precision: %f' % precision)
                print('Recall: %f' % recall)
                print('F1: %f' % f1)
                print('-')

            f1_average = sum(f1_scores) / len(f1_scores)
            print('Sentence 0 F1 Average: %f' % f1_average)

        self.model = model

    def predict(self, dataset):
        """
        Generates predictions over a string or a medaCy dataset

        :param dataset: a string or medaCy Dataset to predict
        :param prediction_directory: the directory to write predictions if doing bulk prediction
                                     (default: */prediction* sub-directory of Dataset)
        """
        if not isinstance(dataset, (Dataset, str)):
            raise TypeError("Must pass in an instance of Dataset")
        if self.model is None:
            raise ValueError("Must fit or load a pickled model before predicting")

        model = self.model

        if isinstance(dataset, Dataset):
            if prediction_directory is None:
                prediction_directory = str(dataset.data_directory) + "/predictions/"

            if isdir(prediction_directory):
                logging.warning("Overwriting existing predictions")
            else:
                makedirs(prediction_directory)

            for data_file in dataset.get_data_files():
                logging.info("Predicting file: %s", data_file.file_name)

                with open(data_file.get_text_path(), 'r') as source_text_file:
                    text = source_text_file.read()

                doc = nlp(text)

                tokens = []
                for token in doc:
                    tokens.append(str(token))

                segmented_tokens = self.get_segments(tokens)

                predictions = []

                for ent in doc.ents:
                    predictions.append((ent.label_, ent.start_char, ent.end_char, ent.text))

                annotations = construct_annotations_from_tuples(text, predictions)

                prediction_filename = join(prediction_directory, data_file.file_name + ".ann")
                logging.debug("Writing to: %s", prediction_filename)
                annotations.to_ann(write_location=prediction_filename)

        if isinstance(dataset, str):
            doc = nlp(dataset)

            entities = []

            for ent in doc.ents:
                entities.append((ent.start_char, ent.end_char, ent.label_))

            return entities

    def save(self, path='nameless-model.pt'):
        torch.save(self.model, path)

    def load(self, path='nameless-model.pt'):
        model = torch.load(path)
        model.eval()