import React from 'react';
import PropTypes from 'prop-types';
import './UploadTestForm.scss';

const CTInput = (props) => {
  const {
    cell,
    handleChangeCellValue,
  } = props;
  return (
    <div className="ct-input-box">
      <div className="ct-input-box-label">
        {cell.label}
      </div>
      <div className="ct-input-box-input">
        <input type="text" name={cell.label} value={cell.value} onChange={handleChangeCellValue} />
        {' Ct'}
      </div>
    </div>
  );
};

CTInput.propTypes = {
  cell: PropTypes.shape({
    label: PropTypes.string,
    value: PropTypes.string,
  }),
  handleChangeCellValue: PropTypes.func.isRequired,
};

CTInput.defaultProps = {
  cell: {
    label: '',
    value: '',
  },
};

const UploadTestForm = (props) => {
  console.log('props: ', props);
  const { cellData, handleChangeCellValue } = props;
  return (
    <div className="upload-test-form">
      <div className="upload-test-form__title">
        Input Cycle Time
      </div>
      {cellData.map((cell) => (
        <CTInput
          key={cell.label}
          cell={cell}
          handleChangeCellValue={handleChangeCellValue}
        />
      ))}
    </div>
  );
};

UploadTestForm.propTypes = {
  cellData: PropTypes.arrayOf(PropTypes.shape({})),
  handleChangeCellValue: PropTypes.func.isRequired,
};

UploadTestForm.defaultProps = {
  cellData: [],
};

export default UploadTestForm;
